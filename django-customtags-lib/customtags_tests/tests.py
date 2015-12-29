
import sys
import unittest
import warnings

from copy import copy

from django import template
from django.template.base import builtins, TextNode, VariableNode
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from customtags.lexer import Lexer, Token, TokenStream, TokenStreamIterator
from customtags.expr_parser import ExprParser
from customtags.tokens import *
from customtags import arguments, core, exceptions, utils, parser, helpers, \
    values, decorators

from _settings_patcher import *
from utils import pool, Renderer


## These are the expression parser test configurations

EXPR_ADD = "var + 1"
EXPR_FUNC = "add1(var)"
EXPR_JINJA_FILTER = "var|default(def)"
EXPR_DJANGO_FILTER = "var|default:def"
EXPR_DJANGO_FILTER_CHAIN = "var|default:def|upper"
EXPR_DJANGO_TRANS = "_(translate)"
EXPR_LITERAL_TRANS = '_("Literal String")'
EXPR_CHAIN_VARS = 'variable.member'
EXPR_DICT_CONST = 'variable["member"]'
EXPR_DICT_VAR = 'variable[member_var]'
EXPR_IF = '1 if False else 2'
EXPR_GTE = '1 >= 2'
EXPR_LT = '2 < 5'
EXPR_EQ = '7 == 5'

TOKEN_MAP = {
    EXPR_ADD : [TOKEN_NAME, TOKEN_ADD, TOKEN_INTEGER],
    EXPR_FUNC : [TOKEN_NAME, TOKEN_LPAREN, TOKEN_NAME, TOKEN_RPAREN],
    EXPR_JINJA_FILTER : [TOKEN_NAME, TOKEN_PIPE, TOKEN_NAME, TOKEN_LPAREN, 
                         TOKEN_NAME, TOKEN_RPAREN],
    EXPR_DJANGO_FILTER : [TOKEN_NAME, TOKEN_PIPE, TOKEN_NAME, TOKEN_COLON, TOKEN_NAME],
    EXPR_DJANGO_FILTER_CHAIN : [TOKEN_NAME, TOKEN_PIPE, TOKEN_NAME, TOKEN_COLON, 
                                TOKEN_NAME, TOKEN_PIPE, TOKEN_NAME],
    EXPR_DJANGO_TRANS : [TOKEN_NAME, TOKEN_LPAREN, TOKEN_NAME, TOKEN_RPAREN],
    EXPR_CHAIN_VARS : [TOKEN_NAME, TOKEN_DOT, TOKEN_NAME], 
    EXPR_DICT_CONST : [TOKEN_NAME, TOKEN_LBRACKET, TOKEN_STRING, TOKEN_RBRACKET], 
    EXPR_DICT_VAR : [TOKEN_NAME, TOKEN_LBRACKET, TOKEN_NAME, TOKEN_RBRACKET], 
    EXPR_IF : [TOKEN_INTEGER, TOKEN_NAME, TOKEN_NAME, TOKEN_NAME, TOKEN_INTEGER], 
    EXPR_GTE : [TOKEN_INTEGER, TOKEN_GTEQ, TOKEN_INTEGER],
    EXPR_LT : [TOKEN_INTEGER, TOKEN_LT, TOKEN_INTEGER],
    EXPR_EQ : [TOKEN_INTEGER, TOKEN_EQ, TOKEN_INTEGER],
}

RESOLVE_MAP = {
    EXPR_ADD : [3, {"var":2}],
    EXPR_FUNC : [2, {"var":1, "add1":lambda x: x+1}],
    EXPR_JINJA_FILTER : ["default", {"var":None, "def":"default"}],
    EXPR_DJANGO_FILTER : ["default", {"var":None, "def":"default"}],
    EXPR_DJANGO_FILTER_CHAIN : ["VALUE", {"var":"value","def":"default"}],
    EXPR_DJANGO_TRANS : ["first", {"translate":"first"}],
    EXPR_LITERAL_TRANS : ["Literal String", {}],
    EXPR_CHAIN_VARS : [22, {"variable":{"member":22}}],
    EXPR_DICT_CONST : [44, {"variable":{"member":44}}],
    EXPR_DICT_VAR : [55, {"member_var":"member","variable":{"member":55}}],
    EXPR_IF : [2, {}],
    EXPR_GTE : [False, {}],
    EXPR_LT : [True, {}],
    EXPR_EQ : [False, {}],
}


class DummyTokens(list):
    def __init__(self, *tokens, **kwargs):
        tagname = kwargs['tagname'] if 'tagname' in kwargs else 'dummy_tag'
        super(DummyTokens, self).__init__([tagname] + list(tokens))
        
    def split_contents(self):
        return self

    @property
    def contents(self):
        return " ".join([str(item) for item in self])


class DummyParser(object):
    def compile_filter(self, token):
        return values.StaticValue(token)

    def find_filter(self, token):
        from django.template.base import builtins
        filters = {}
        for lib in builtins:
            filters.update(lib.filters)
        return filters[token] 

dummy_parser = DummyParser()


class DummyContainer(object):
    def __init__(self, tagname="dummy_tag"):
        self.tag_args = []
        self.tag_kwargs = {}
        self.tagname = tagname


class _Warning(object):
    def __init__(self, message, category, filename, lineno):
        self.message = message
        self.category = category
        self.filename = filename
        self.lineno = lineno


class TokenStreamTestCase(TestCase):
    test_tokens = [Token(TOKEN_BLOCK_BEGIN, ''),
                   Token(TOKEN_BLOCK_END, '')]

    def test_simple(self):
        ts = TokenStream(self.test_tokens)
        assert ts.current.type is TOKEN_BLOCK_BEGIN
        assert bool(ts)
        assert not bool(ts.eos)
        next(ts)
        assert ts.current.type is TOKEN_BLOCK_END
        assert bool(ts)
        assert not bool(ts.eos)
        next(ts)
        assert ts.current.type is TOKEN_EOF
        assert ts.size == 0
        assert not bool(ts)
        assert bool(ts.eos)

    def test_look(self):
        ts = TokenStream(self.test_tokens)
        assert ts.current.type is TOKEN_BLOCK_BEGIN
        assert ts.look().type is TOKEN_BLOCK_END
        assert bool(ts)
        assert not bool(ts.eos)
        next(ts)
        assert ts.current.type is TOKEN_BLOCK_END
        assert ts.look().type is TOKEN_EOF
        assert bool(ts)
        assert not bool(ts.eos)
        next(ts)
        assert ts.current.type is TOKEN_EOF
        assert ts.size == 0
        assert not bool(ts)
        assert bool(ts.eos)

    def test_iter(self):
        token_types = [t.type for t in TokenStream(self.test_tokens)]
        assert token_types == ['block_begin', 'block_end', ]

    def test_copy(self):
        ts1 = TokenStream(self.test_tokens)
        assert ts1.size == 2
        ts2 = copy(ts1)
        assert ts1.size == ts2.size
        next(ts2)
        assert ts1.size > ts2.size


class LexerTestCase(TestCase):
    def setUp(self):
        self.lexer = Lexer()

    def _do_expr_test(self, expr):
        results = list(self.lexer.tokenize(expr))
        tokentypes = TOKEN_MAP[expr]
        self.assertEqual(len(results), len(tokentypes))
        for index, result in enumerate(results):
            self.assertEqual(result.type, tokentypes[index])

    def test_add_expr(self):
        self._do_expr_test(EXPR_ADD)

    def test_simple_func_expr(self):
        self._do_expr_test(EXPR_FUNC)

    def test_jinja_filter_expr(self):
        self._do_expr_test(EXPR_JINJA_FILTER)

    def test_django_filter_expr(self):
        self._do_expr_test(EXPR_DJANGO_FILTER)
    
    def test_django_filter_chain_expr(self):
        self._do_expr_test(EXPR_DJANGO_FILTER_CHAIN)
    
    def test_django_trans(self):
        self._do_expr_test(EXPR_DJANGO_TRANS)

    def test_chain_vars(self):
        self._do_expr_test(EXPR_CHAIN_VARS)

    def test_dict_const(self):
        self._do_expr_test(EXPR_DICT_CONST)

    def test_dict_var(self):
        self._do_expr_test(EXPR_DICT_VAR)

    def test_if(self):
        self._do_expr_test(EXPR_IF)

    def test_equality(self):
        self._do_expr_test(EXPR_EQ)

    def test_lessthan(self):
        self._do_expr_test(EXPR_LT)

    def test_greaterthanequal(self):
        self._do_expr_test(EXPR_GTE)


class ParserTestCase(TestCase):
    def setUp(self):
        self.lexer = Lexer()
        self.parser = ExprParser()

    def _do_resolve_expr(self, expr):
        context = RESOLVE_MAP[expr][1]
        expected = RESOLVE_MAP[expr][0]
        self._test_expr(expr, context, expected)

    def _test_expr(self, expr, context, expected):
        stream = self.lexer.tokenize(expr)
        result = self.parser.parse(stream, dummy_parser)        
        self.assertEqual(result.resolve(context), expected)

    def test_add_expr(self):
        self._do_resolve_expr(EXPR_ADD)

    def test_simple_func_expr(self):
        self._do_resolve_expr(EXPR_FUNC)

    def test_jinja_filter_expr(self):
        self._do_resolve_expr(EXPR_JINJA_FILTER)

    def test_django_filter_expr(self):
        self._do_resolve_expr(EXPR_DJANGO_FILTER)

    def test_django_filter_chain_expr(self):
        self._do_resolve_expr(EXPR_DJANGO_FILTER_CHAIN)

    def test_django_trans(self):
        self._do_resolve_expr(EXPR_DJANGO_TRANS)

    def test_chain_vars(self):
        self._do_resolve_expr(EXPR_CHAIN_VARS)

    def test_dict_const(self):
        self._do_resolve_expr(EXPR_DICT_CONST)

    def test_dict_var(self):
        self._do_resolve_expr(EXPR_DICT_VAR)

    def test_if(self):
        self._do_resolve_expr(EXPR_IF)

    def test_equality(self):
        self._do_resolve_expr(EXPR_EQ)

    def test_lessthan(self):
        self._do_resolve_expr(EXPR_LT)

    def test_greaterthanequal(self):
        self._do_resolve_expr(EXPR_GTE)

    def test_function_arguments(self):
        def concat(list1, list2):
            return list1 + list2
        def add(num1, num2=1):
            return num1 + num2
        def sum(*args):
            return reduce(lambda x, y: x + y, args)
        def makedict(**kwargs):
            return kwargs

        ctx = {
            "concat" : concat,
            "add" : add,
            "sum" : sum,
            "makedict" : makedict,
        }
        def c(d):
            d = copy(d)
            d.update(ctx)
            return d

        test_concat = "concat([1,2,3], list)"
        test_add1 = "add(1)"
        test_add2 = "add(2, 2)"
        test_add3 = "add(num1=3, num2=3)"
        test_add4 = "add(num1=4)"
        test_add5 = "add(bad, num2=1)"
        test_add6 = "add(1, num2=bad)"
        test_sum1 = "sum(1,2,3,4)"
        test_sum2 = "sum(1,2,3,var)"
        test_sum3 = "sum(*list)"
        test_sum4 = "sum(1,2,3,bad)"
        test_sum5 = "sum(*bad)"
        test_dict1 = "makedict(one=1, two=2, three=3)"
        test_dict2 = "makedict(**dict)"
        test_dict3 = "makedict(one=1, two=2, three=bad)"
        test_dict4 = "makedict(**bad)"
        test_undefined = "undefined(arg)"

        ## TODO: use the correct exceptions
        self._test_expr(test_concat, c({"list":[4,5,6]}), [1,2,3,4,5,6])
        self._test_expr(test_add1, ctx, 2)
        self._test_expr(test_add2, ctx, 4)
        self._test_expr(test_add3, ctx, 6)
        self._test_expr(test_add4, ctx, 5)
        self.assertRaises(TypeError, self._test_expr, test_add5, ctx, 0)
        self.assertRaises(TypeError, self._test_expr, test_add6, ctx, 0)
        self._test_expr(test_sum1, ctx, 10)
        self._test_expr(test_sum2, c({"var":5}), 11)
        self._test_expr(test_sum3, c({"list":[1,2,3,4,5]}), 15)
        self.assertRaises(TypeError, self._test_expr, test_sum4, ctx, 0)
        self.assertRaises(ValueError, self._test_expr, test_sum5, ctx, 0)
        self._test_expr(test_dict1, ctx, {"one":1, "two":2, "three":3})
        self._test_expr(test_dict2, c({"dict":{"a":"1","b":"2"}}), {"a":"1", "b":"2"})
        self._test_expr(test_dict3, ctx, {"one":1, "two":2, "three":""})
        #self.assertRaises(ValueError, self._test_expr, test_dict3, ctx, 0)
        self.assertRaises(ValueError, self._test_expr, test_dict4, ctx, 0)
        self.assertRaises(NameError, self._test_expr, test_undefined, c({"arg":1}), 0)


def _collectWarnings(observeWarning, f, *args, **kwargs):
    def showWarning(message, category, filename, lineno, file=None, line=None):
        assert isinstance(message, Warning)
        observeWarning(_Warning(
                message.args[0], category, filename, lineno))

    # Disable the per-module cache for every module otherwise if the warning
    # which the caller is expecting us to collect was already emitted it won't
    # be re-emitted by the call to f which happens below.
    for v in sys.modules.itervalues():
        if v is not None:
            try:
                v.__warningregistry__ = None
            except: # pragma: no cover
                # Don't specify a particular exception type to handle in case
                # some wacky object raises some wacky exception in response to
                # the setattr attempt.
                pass

    origFilters = warnings.filters[:]
    origShow = warnings.showwarning
    warnings.simplefilter('always')
    try:
        warnings.showwarning = showWarning
        result = f(*args, **kwargs)
    finally:
        warnings.filters[:] = origFilters
        warnings.showwarning = origShow
    return result


class CustomtagsTests(TestCase):
    urls = 'customtags_tests.test_urls'

    def failUnlessWarns(self, category, message, f, *args, **kwargs):
        warningsShown = []
        result = _collectWarnings(warningsShown.append, f, *args, **kwargs)

        if not warningsShown: # pragma: no cover
            self.fail("No warnings emitted")
        first = warningsShown[0]
        for other in warningsShown[1:]: # pragma: no cover
            if ((other.message, other.category)
                != (first.message, first.category)):
                self.fail("Can't handle different warnings")
        self.assertEqual(first.message, message)
        self.assertTrue(first.category is category)

        return result
    assertWarns = failUnlessWarns

    def failUnlessRaises(self, excClass, callableObj, *args, **kwargs):
        """This is here to accomodate cases where debug is on in settings."""
        try:
            super(CustomtagsTests, self).failUnlessRaises(excClass, callableObj, 
                                                          *args, **kwargs)
        except template.TemplateSyntaxError, e:
            if hasattr(e, "exc_info") and e.exc_info[0] is excClass:
                return
            else:
                raise
    assertRaises = failUnlessRaises
    
    def _tag_tester(self, templates=[], *classes, **kwargs):
        """
        Helper method to test a template tag by rendering it and checkout output.
        
        *klass* is a template tag class (subclass of core.Tag)
        *templates* is a sequence of a triple (template-string, output-string,
        context) 
        """
        lib = kwargs["library"] if "library" in kwargs else template.Library()
        for cls in classes:
            lib.tag(cls.as_tag())
            self.assertTrue(cls.name in lib.tags)

        builtins.append(lib)

        for tpl, out, ctx in templates:
            t = template.Template(tpl)
            c = template.Context(ctx)
            s = t.render(c)
            self.assertEqual(s, out)
            for key, value in ctx.items():
                self.assertEqual(c.get(key), value)            
        builtins.remove(lib)
    
    def _decorator_tester(self, templates, library):
        """
        Helper method to test a template tag by rendering it and checkout output.
        
        *templates* is a sequence of a triple (template-string, output-string,
        context) 
        *library* is a registration library for registering tags
        """
        builtins.append(library)

        for tpl, out, ctx in templates:
            t = template.Template(tpl)
            c = template.Context(ctx)
            s = t.render(c)
            self.assertEqual(s, out)
        builtins.remove(library)
    
    def test_01_simple_parsing(self):
        """
        Test very basic single argument parsing
        """
        options = core.Options(
            arguments.Argument('myarg'),
        )
        options.initialize('dummy_tag')

        dummy_tokens = DummyTokens('myval')
        dummy_container = DummyContainer()

        options.parse(dummy_parser, dummy_tokens, dummy_container)
        self.assertEqual(dummy_container.tag_args, [])
        self.assertEqual(len(dummy_container.tag_kwargs), 1)

        dummy_context = {"myval" : 1}
        self.assertEqual(dummy_container.tag_kwargs['myarg'].resolve(dummy_context), 1)

        dummy_tokens = DummyTokens('myval', 'myval2')
        dummy_container = DummyContainer()
        self.assertRaises(exceptions.TooManyArguments, options.parse, 
                          dummy_parser, dummy_tokens, dummy_container)
        
    def test_02_optional(self):
        """
        Test basic optional argument parsing
        """
        options = core.Options(
            arguments.Argument('myarg'),
            arguments.Argument('optarg', required=False, default=None),
        )
        options.initialize('dummy_tag')

        dummy_tokens = DummyTokens('myval')
        dummy_container = DummyContainer()
        options.parse(dummy_parser, dummy_tokens, dummy_container)
        self.assertEqual(dummy_container.tag_args, [])
        self.assertEqual(len(dummy_container.tag_kwargs), 2)

        dummy_context = {"myval":2}
        self.assertEqual(dummy_container.tag_kwargs['myarg'].resolve(dummy_context), 2)
        self.assertEqual(dummy_container.tag_kwargs['optarg'].resolve(dummy_context), None)

        dummy_tokens = DummyTokens('myval', 'optval')
        dummy_container = DummyContainer()
        options.parse(dummy_parser, dummy_tokens, dummy_container)
        self.assertEqual(dummy_container.tag_args, [])
        self.assertEqual(len(dummy_container.tag_kwargs), 2)

        dummy_context = {'myval':3, 'optval':4}
        self.assertEqual(dummy_container.tag_kwargs['myarg'].resolve(dummy_context), 3)
        self.assertEqual(dummy_container.tag_kwargs['optarg'].resolve(dummy_context), 4)
        
    def test_03_breakpoints(self):
        """
        Test parsing with breakpoints
        """
        options = core.Options(
            arguments.Argument('myarg'),
            'as',
            arguments.Argument('varname'),
            'using',
            arguments.Argument('using'),
        )
        options.initialize('dummy_tag')

        dummy_tokens = DummyTokens('myval')
        dummy_container = DummyContainer()
        self.assertRaises(exceptions.TooFewArguments, options.parse, dummy_parser, 
                          dummy_tokens, dummy_container)
        dummy_tokens = DummyTokens('myval', 'myname')
        dummy_container = DummyContainer()
        self.assertRaises(exceptions.BreakpointExpected, options.parse, dummy_parser, 
                          dummy_tokens, dummy_container)
        dummy_tokens = DummyTokens('myval', 'as', 'myname', 'something')
        dummy_container = DummyContainer()
        self.assertRaises(exceptions.BreakpointExpected, options.parse, dummy_parser, 
                          dummy_tokens, dummy_container)

        dummy_tokens = DummyTokens('myval', 'as', 'myname', 'using', 'something')
        dummy_container = DummyContainer()
        options.parse(dummy_parser, dummy_tokens, dummy_container)
        self.assertEqual(dummy_container.tag_args, [])
        self.assertEqual(len(dummy_container.tag_kwargs), 3)
        dummy_context = {"myval":"MYVAL", "myname":"MYNAME", "something":"SOMETHING"}
        self.assertEqual(dummy_container.tag_kwargs['myarg'].resolve(dummy_context), 'MYVAL')
        self.assertEqual(dummy_container.tag_kwargs['varname'].resolve(dummy_context), 'MYNAME')
        self.assertEqual(dummy_container.tag_kwargs['using'].resolve(dummy_context), 'SOMETHING')
        
    def test_04_flag(self):
        """
        Test flag arguments
        """
        options = core.Options(
            arguments.Flag('myflag', true_values=['on'], false_values=['off'])
        )
        options.initialize('dummy_flag_tag1')

        dummy_context = {}
        dummy_tokens = DummyTokens('on', tagname="dummy_flag_tag1")
        dummy_container = DummyContainer("dummy_flag_tag1")
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(kwargs['myflag'].resolve(dummy_context), True)

        dummy_tokens = DummyTokens('off', tagname="dummy_flag_tag1")
        dummy_container = DummyContainer("dummy_flag_tag1")
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(kwargs['myflag'].resolve(dummy_context), False)

        dummy_tokens = DummyTokens('myval', tagname="dummy_flag_tag1")
        dummy_container = DummyContainer("dummy_flag_tag1")
        self.assertRaises(exceptions.InvalidFlag, options.parse, dummy_parser, 
                          dummy_tokens, dummy_container)
        self.assertRaises(ImproperlyConfigured, arguments.Flag, 'myflag')

        # test case sensitive flag
        options = core.Options(
            arguments.Flag('myflag', true_values=['on'], default=False, case_sensitive=True)
        )
        options.initialize('dummy_flag_tag2')

        dummy_tokens = DummyTokens('On', tagname="dummy_flag_tag2")
        dummy_container = DummyContainer("dummy_flag_tag2")
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        self.assertRaises(exceptions.TooManyArguments, options.parse, 
                          dummy_parser, dummy_tokens, dummy_container)

        dummy_tokens = DummyTokens('on', tagname="dummy_flag_tag2")
        dummy_container = DummyContainer("dummy_flag_tag2")
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(kwargs['myflag'].resolve(dummy_context), True)

        # test multi-flag
        options = core.Options(
            arguments.Flag('flagone', true_values=['on'], default=False),
            arguments.Flag('flagtwo', false_values=['off'], default=True),
        )
        options.initialize('dummy_flag_tag3')

        dummy_tokens = DummyTokens('on', 'off', tagname="dummy_flag_tag3")
        dummy_container = DummyContainer("dummy_flag_tag3")
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(kwargs['flagone'].resolve(dummy_context), True)
        self.assertEqual(kwargs['flagtwo'].resolve(dummy_context), False)

        dummy_tokens = DummyTokens('off', tagname="dummy_flag_tag3")
        dummy_container = DummyContainer("dummy_flag_tag3")
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(kwargs['flagone'].resolve(dummy_context), False)
        self.assertEqual(kwargs['flagtwo'].resolve(dummy_context), False)

        dummy_tokens = DummyTokens(tagname="dummy_flag_tag3")
        dummy_container = DummyContainer("dummy_flag_tag3")
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(kwargs['flagone'].resolve(dummy_context), False)
        self.assertEqual(kwargs['flagtwo'].resolve(dummy_context), True)
        
    def test_05_multi_value(self):
        """
        Test simple multi value arguments
        """
        options = core.Options(
            arguments.MultiValueArgument('myarg')
        )
        options.initialize('dummy_tag')

        # test single token MVA
        dummy_tokens = DummyTokens('myval')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(len(kwargs), 1)
        dummy_context = {"myval": "val1", "myval2": "val2", "myval3": "val3"}
        # test resolving to list
        self.assertEqual(kwargs['myarg'].resolve(dummy_context), ["val1"])

        # test double token MVA
        dummy_tokens = DummyTokens('myval', 'myval2')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(len(kwargs), 1)
        self.assertEqual(kwargs['myarg'].resolve(dummy_context), ['val1', 'val2'])
        # test triple token MVA

        dummy_tokens = DummyTokens('myval', 'myval2', 'myval3')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(len(kwargs), 1)
        self.assertEqual(kwargs['myarg'].resolve(dummy_context), ['val1', 'val2', 'val3'])

        # test max_values option
        options = core.Options(
            arguments.MultiValueArgument('myarg', max_values=2)
        )
        options.initialize('dummy_tag')

        dummy_tokens = DummyTokens('myval')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(len(kwargs), 1)
        dummy_context = {"myval": 11, "myval2": 22, "myval3": 33}
        self.assertEqual(kwargs['myarg'].resolve(dummy_context), [11])

        dummy_tokens = DummyTokens('myval', 'myval2')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(len(kwargs), 1)
        self.assertEqual(kwargs['myarg'].resolve(dummy_context), [11, 22])

        dummy_tokens = DummyTokens('myval', 'myval2', 'myval3')
        dummy_container = DummyContainer()
        self.assertRaises(exceptions.TooManyArguments, options.parse, dummy_parser, 
                          dummy_tokens, dummy_container)

        # test no resolve
        options = core.Options(
            arguments.MultiValueArgument('myarg', resolve=False)
        )
        options.initialize('dummy_tag')

        dummy_tokens = DummyTokens('myval', "'myval2'")
        dummy_container = DummyContainer()
        dummy_context = {"myval": 101, "myval2": 202, "myval3": 303}
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(kwargs['myarg'].resolve(dummy_context), ['myval', 'myval2'])
        
    def test_06_complex(self):
        """
        test a complex tag option parser
        """
        options = core.Options(
            arguments.Argument('singlearg'),
            arguments.MultiValueArgument('multiarg', required=False),
            'as',
            arguments.Argument('varname', required=False),
            'safe',
            arguments.Flag('safe', true_values=['true'], false_values=['false'], default=False)
        )
        options.initialize('dummy_tag')
        dummy_context = {}

        # test simple 'all arguments given'
        dummy_tokens = DummyTokens(1, 2, 3, 'as', 4, 'safe', 'true')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(len(kwargs), 4)
        for key, value in [('singlearg', 1), ('multiarg', [2,3]), ('varname', 4), ('safe', True)]:
            self.assertEqual(kwargs[key].resolve(dummy_context), value)

        # test 'only first argument given'
        dummy_tokens = DummyTokens(1)
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(len(kwargs), 4)
        for key, value in [('singlearg', 1), ('multiarg', []), ('varname', None), ('safe', False)]:
            self.assertEqual(kwargs[key].resolve(dummy_context), value)

        # test first argument and last argument given
        dummy_tokens = DummyTokens(2, 'safe', 'false')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        self.assertEqual(args, [])
        self.assertEqual(len(kwargs), 4)
        for key, value in [('singlearg', 2), ('multiarg', []), ('varname', None), ('safe', False)]:
            self.assertEqual(kwargs[key].resolve(dummy_context), value)
            
    def test_07_cycle(self):
        """
        This test re-implements django's cycle tag (because it's quite crazy)
        and checks if it works.
        """
        from itertools import cycle as itertools_cycle
        
        class Cycle(core.Tag):
            name = 'classy_cycle'
            
            options = core.Options(
                arguments.MultiValueArgument('values'),
                'as',
                arguments.Argument('varname', required=False, resolve=False),
            )
            
            def render_tag(self, context, values, varname):
                if self not in context.render_context:
                    context.render_context[self] = itertools_cycle(values)
                cycle_iter = context.render_context[self]
                value = cycle_iter.next()
                if varname:
                    context[varname] = value
                return value

        lib = template.Library()
        lib.tag(Cycle.as_tag())
        self.assertTrue('classy_cycle' in lib.tags)
        origtpl = template.Template("""
            {% for thing in sequence %}{% cycle "1" "2" "3" "4" %}{% endfor %}
        """)
        sequence = [1,2,3,4,5,6,7,8,9,10]
        context = template.Context({'sequence': sequence})
        original = origtpl.render(context)
        builtins.insert(0, lib)
        classytpl = template.Template("""
            {% for thing in sequence %}{% classy_cycle "1" "2" "3" "4" %}{% endfor %}
        """)
        classy = classytpl.render(context)
        self.assertEqual(original, classy)
        origtpl = template.Template("""
            {% for thing in sequence %}{% cycle "1" "2" "3" "4" as myvarname %}{% endfor %}
        """)
        sequence = [1,2,3,4,5,6,7,8,9,10]
        context = template.Context({'sequence': sequence})
        original = origtpl.render(context)
        builtins.insert(0, lib)
        classytpl = template.Template("""
            {% for thing in sequence %}{% classy_cycle "1" "2" "3" "4" as myvarname %}{% endfor %}
        """)
        classy = classytpl.render(context)
        self.assertEqual(original, classy)
        
    def test_08_naming(self):
        # test implicit naming
        class MyTag(core.Tag):
            pass
        lib = template.Library()
        lib.tag(MyTag.as_tag())
        self.assertTrue('my_tag' in lib.tags, "'my_tag' not in %s" % lib.tags.keys())
        # test explicit naming
        class MyTag2(core.Tag):
            name = 'my_tag_2'
        lib = template.Library()
        lib.tag(MyTag2.as_tag())
        self.assertTrue('my_tag_2' in lib.tags, "'my_tag_2' not in %s" % lib.tags.keys())
        # test named registering
        lib = template.Library()
        lib.tag('my_tag_3', MyTag.as_tag())
        self.assertTrue('my_tag_3' in lib.tags, "'my_tag_3' not in %s" % lib.tags.keys())
        self.assertTrue('my_tag' not in lib.tags, "'my_tag' in %s" % lib.tags.keys())
        lib = template.Library()
        lib.tag('my_tag_4', MyTag2.as_tag())
        self.assertTrue('my_tag_4' in lib.tags, "'my_tag_4' not in %s" % lib.tags.keys())
        self.assertTrue('my_tag2' not in lib.tags, "'my_tag2' in %s" % lib.tags.keys())
        
    def test_09_hello_world(self):
        class Hello(core.Tag):
            options = core.Options(
                arguments.Argument('name', required=False, default='world'),
                'as',
                arguments.Argument('varname', required=False, resolve=False)
            )
        
            def render_tag(self, context, name, varname):
                output = 'hello %s' % name
                if varname:
                    context[varname] = output
                    return ''
                return output

        tpls = [
            ('{% hello %}', 'hello world', {}),
            ('{% hello "customtags" %}', 'hello customtags', {}),
            ('{% hello as myvar %}', '', {'myvar': 'hello world'}),
            ('{% hello "my friend" as othervar %}', '', {'othervar': 'hello my friend'})
        ]
        self._tag_tester(tpls, Hello)
                
    def test_10_django_vs_classy(self):
        pool.autodiscover()
        for tagname, data in pool:
            controls = data.get('controls', None)
            if not controls: # pragma: no cover
                continue
            tag = data['tag']                
            renderer = Renderer(tag)
            i = 0
            for djstring, ctstring, ctx in controls:
                i += 1
                dj = renderer.django(djstring, ctx)
                cy = renderer.classy(ctstring, ctx)
                self.assertNotEqual(djstring, ctstring)
                self.assertEqual(dj, cy,
                    ("Classytag implementation of %s (control %s) returned "
                     "something other than the official tag:\n"
                     "Classy: %r\nDjango: %r" % (tagname, i, cy, dj))
                )
    
    def test_11_blocks(self):
        class Blocky(core.Tag):
            options = core.Options(
                blocks=['a', 'b', 'c', 'd', 'e'],
            )
            
            def render_tag(self, context, **nodelists):
                tpl = "%(a)s;%(b)s;%(c)s;%(d)s;%(e)s"
                data = {}
                for key, value in nodelists.items():
                    data[key] = value.render(context)
                return tpl % data
        templates = [
            ('{% blocky %}1{% a %}2{% b %}3{% c %}4{% d %}5{% e %}', '1;2;3;4;5', {},),
            ('{% blocky %}12{% b %}3{% c %}4{% d %}5{% e %}', '12;;3;4;5', {},),
            ('{% blocky %}123{% c %}4{% d %}5{% e %}', '123;;;4;5', {},),
            ('{% blocky %}1234{% d %}5{% e %}', '1234;;;;5', {},),
            ('{% blocky %}12345{% e %}', '12345;;;;', {},),
            ('{% blocky %}1{% a %}23{% c %}4{% d %}5{% e %}', '1;23;;4;5', {},),
            ('{% blocky %}1{% a %}23{% c %}45{% e %}', '1;23;;45;', {},),
        ]
        self._tag_tester(templates, Blocky)
        
    def test_12_astag(self):
        class Dummy(helpers.AsTag):
            options = core.Options(
                'as',
                arguments.Argument('varname', resolve=False, required=False),
            )
            
            def get_value(self, context):
                return "dummy"
        templates = [
            ('{% dummy %}:{{ varname }}', 'dummy:', {},),
            ('{% dummy as varname %}:{{ varname }}', ':dummy', {},),
        ]
        self._tag_tester(templates, Dummy)
        
    def test_13_inclusion_tag(self):
        class Inc(helpers.InclusionTag):
            template = 'test.html'
            
            options = core.Options(
                arguments.Argument('var'),
            )
            
            def get_context(self, context, var):
                return {'var': var}
        templates = [
            ('{% inc var %}', 'inc', {'var': 'inc'},),
        ]
        self._tag_tester(templates, Inc)
        class Inc2(helpers.InclusionTag):
            template = 'test.html'
        templates = [
            ('{% inc2 %}', '', {},),
        ]
        self._tag_tester(templates, Inc2)
        
    def test_14_integer_variable(self):

        from django.conf import settings
        options = core.Options(
            arguments.IntegerArgument('integer', resolve=False),
        )
        options.initialize('dummy_tag')

        # this is settings dependant!
        old = settings.DEBUG
        # test okay
        settings.DEBUG = False

        dummy_tokens = DummyTokens('1')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        dummy_context = {}
        self.assertEqual(kwargs['integer'].resolve(dummy_context), 1)

        # test warning
        dummy_tokens = DummyTokens('one')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        dummy_context = {}
        message = arguments.IntegerValue.errors['clean'] % {'value': repr('one')}
        self.assertWarns(exceptions.TemplateSyntaxWarning, message, kwargs['integer'].resolve, dummy_context)
        self.assertEqual(kwargs['integer'].resolve(dummy_context), values.IntegerValue.value_on_error)

        # test exception
        settings.DEBUG = True

        dummy_tokens = DummyTokens('one')
        dummy_container = DummyContainer()
        args, kwargs = dummy_container.tag_args, dummy_container.tag_kwargs
        options.parse(dummy_parser, dummy_tokens, dummy_container)

        dummy_context = {}
        message = values.IntegerValue.errors['clean'] % {'value': repr('one')}
        self.assertRaises(template.TemplateSyntaxError, kwargs['integer'].resolve, dummy_context)

        # test the same as above but with resolving
        settings.DEBUG = False
        assertTrue = self.assertTrue

        class IntegerTag(core.Tag):
            options = core.Options(
                arguments.IntegerArgument('integer')
            )
            
            def render_tag(self, context, integer):
                return integer
            
        lib = template.Library()
        lib.tag(IntegerTag.as_tag())
        builtins.append(lib)
        self.assertTrue('integer_tag' in lib.tags)
        # test okay
        tpl = template.Template("{% integer_tag i %}")
        context = template.Context({'i': '1'})
        self.assertEqual(tpl.render(context), '1')
        # test warning
        context = template.Context({'i': 'one'})
        message = values.IntegerValue.errors['clean'] % {'value': repr('one')}
        self.assertWarns(exceptions.TemplateSyntaxWarning, message, tpl.render, context)
        self.assertEqual(tpl.render(context), values.IntegerValue.value_on_error)
        # test exception
        settings.DEBUG = True
        context = template.Context({'i': 'one'})
        message = arguments.IntegerValue.errors['clean'] % {'value': repr('one')}
        self.assertRaises(template.TemplateSyntaxError, tpl.render, context)

        # reset settings
        builtins.remove(lib)
        settings.DEBUG = old
        
    def test_15_not_implemented_errors(self):
        lib = template.Library()
        class Fail(core.Tag):
            pass
        class Fail2(helpers.AsTag):
            pass
        class Fail3(helpers.AsTag):
            options = core.Options(
                'as',
            )
        class Fail4(helpers.AsTag):
            options = core.Options(
                'as',
                arguments.Argument('varname', resolve=False),
            )
        class Fail5(helpers.InclusionTag):
            pass
        lib.tag(Fail.as_tag())
        lib.tag(Fail2.as_tag())
        lib.tag(Fail3.as_tag())
        lib.tag(Fail4.as_tag())
        lib.tag(Fail5.as_tag())
        builtins.append(lib)
        self.assertTrue('fail' in lib.tags)
        self.assertTrue('fail2' in lib.tags)
        self.assertTrue('fail3' in lib.tags)
        self.assertTrue('fail4' in lib.tags)
        self.assertTrue('fail5' in lib.tags)
        context = template.Context({})
        tpl = template.Template("{% fail %}")
        self.assertRaises(NotImplementedError, tpl.render, context)
        self.assertRaises(ImproperlyConfigured, template.Template, "{% fail2 %}")
        self.assertRaises(ImproperlyConfigured, template.Template, "{% fail3 %}")
        tpl = template.Template("{% fail4 as something %}")
        self.assertRaises(NotImplementedError, tpl.render, context)
        self.assertRaises(ImproperlyConfigured, template.Template, "{% fail5 %}")
        builtins.remove(lib)
        
    def test_16_too_many_arguments(self):
        lib = template.Library()
        class NoArg(core.Tag):
            pass
        lib.tag(NoArg.as_tag())
        builtins.append(lib)
        self.assertTrue('no_arg' in lib.tags)
        self.assertRaises(exceptions.TooManyArguments, template.Template, "{% no_arg a arg %}")
        builtins.remove(lib)

    def test_17_repetition(self):
        class Switch(core.Tag):
            name = "switch"
            options = core.Options(
                arguments.Argument('state'),
                arguments.Repetition(
                    'cases',
                    arguments.BlockTag(
                        'case',
                        arguments.Argument('value'),
                        arguments.NodeList('nodelist'),
                        arguments.EndTag()
                    ),
                    min_reps = 1
                ),
                arguments.BlockTag(
                    'default',
                    arguments.NodeList("default"),
                    arguments.EndTag()
                ),
                arguments.EndTag()
            )
            def render_tag(self, context, state, cases, default):
                for case in cases:
                    value = case.kwargs['value']
                    if state == value:
                        nodelist = case.kwargs['nodelist']
                        context.push()
                        try:
                            return nodelist.render(context)
                        finally:
                            context.pop()

                context.push()
                try:
                    return default.render(context)
                finally:
                    context.pop()

        tpls = [
            ("""{% switch 1 %}
                  {% case 1 %}ONE{% endcase %}
                  {% case 2 %}TWO{% endcase %}
                  {% default %}DEFAULT{% enddefault %}
                {% endswitch %}""", 'ONE',{}),
            ("""{% switch 2 %}
                  {% case 1 %}ONE{% endcase %}
                  {% case 2 %}TWO{% endcase %}
                  {% default %}DEFAULT{% enddefault %}
                {% endswitch %}""", 'TWO',{}),
            ("""{% switch 3 %}
                  {% case 1 %}ONE{% endcase %}
                  {% case 2 %}TWO{% endcase %}
                  {% default %}DEFAULT{% enddefault %}
                {% endswitch %}""", 'DEFAULT',{}),
        ]
        self._tag_tester(tpls, Switch)

        var_template = """{% switch var %}
                            {% case "A" %}A{% endcase %}
                            {% case "B" %}B{% endcase %}
                            {% case "C" %}C{% endcase %}
                            {% default %}DEFAULT{% enddefault %}
                          {% endswitch %}"""
        tpls = (
            [var_template, "A", { 'var' : "A" }],
            [var_template, "B", { 'var' : "B" }],
            [var_template, "C", { 'var' : "C" }],
            [var_template, "DEFAULT", { 'var' : "D" }],
            [var_template, "DEFAULT", { 'var' : "X" }],
        )
        self._tag_tester(tpls, Switch)

        ## Testing get_nodes_by_type
        lib = template.Library()
        lib.tag(Switch.as_tag())
        builtins.append(lib)
        tmpl = template.Template(var_template)
        nodes = tmpl.nodelist.get_nodes_by_type(TextNode) 
        self.assertEqual(len(nodes),4)
        builtins.remove(lib)

        try:
            self._tag_tester([("""{% switch 1 %}{% default %}DEFAULT{% enddefault %}
                                  {% endswitch %}""","DEFAULT",{})], Switch)
        except exceptions.ArgumentRequiredError, e:
            return

        self.assertTrue(False)


    def test_18_decorators(self):

        lib = template.Library()
        block = decorators.block_decorator(lib)
        
        @block
        def hello(context, nodelist, name="world", as_name="message"):
            context.push()
            context[as_name] = "hello %s" % name
            rendered = nodelist.render(context) 
            context.pop()

            return rendered

        tpls = [
            ('{% hello %}{{ message }}{% endhello %}', 'hello world', {}),
            ('{% hello name="customtags" %}{{ message }}{% endhello %}', 
              'hello customtags', {}),
            ('{% hello "customtags" %}{{ message }}{% endhello %}', 'hello customtags', {}),
            ('{% hello as myvar %}{{ myvar }}{% endhello %}', 'hello world', {}),
            ('{% hello name="my friend" as othervar %}{{ othervar }}{% endhello %}', 
              'hello my friend', {}),
            ('{% hello "my friend" as othervar %}{{ othervar }}{% endhello %}', 
              'hello my friend', {}),
        ]
        self._decorator_tester(tpls, lib)

        lib2 = template.Library()

        @block(lib2, "alt_name")
        def dummy(context, nodelist, as_name="dummy"):
            context.push()
            context[as_name] = "dummy"
            rendered = nodelist.render(context) 
            context.pop()

            return rendered
        
        tpls2 = [
            ('{% alt_name %}{{ dummy }}{% endalt_name %}', 'dummy', {}),
            ('{% alt_name as varname %}{{ varname }}{% endalt_name %}', 'dummy', {}),
        ]
        self._decorator_tester(tpls2, lib2)

        lib3 = template.Library()
        function = decorators.function_decorator(lib3)

        @function
        def hello_func(context, name=None):
            name = name if name is not None else "world"
            return "hello %s" % name

        tpls3 = [
            ('{% hello_func %}', 'hello world', {}),
            ('{% hello_func name="customtags" %}', 'hello customtags', {}),
            ('{% hello_func "customtags" %}', 'hello customtags', {}),
            ('{% hello_func as myvar %}:{{ myvar }}', ':hello world', {}),
            ('{% hello_func name="my friend" as othervar %}{{othervar}}',
              'hello my friend', {}),
            ('{% hello_func "my friend" as othervar %}:{{ othervar }}', 
              ':hello my friend', {}),
        ]
        self._decorator_tester(tpls3, lib3)

        tpls3_b = [
            ('{% hello_func vals.green %}', 'hello verde', { "vals" : { "green" : "verde" } }),
            ('{% hello_func vals.blue %}', 'hello world', { "vals" : { "green" : "verde" } }),
        ]
        self._decorator_tester(tpls3_b, lib3)

        lib4 = template.Library()
        @function(lib4, "alt_func")
        def dummy_func(as_name="dummy"):
            return "dummy"

        tpls4 = [
            ('{% alt_func %}', 'dummy', {}),
            ('{% alt_func as varname %}:{{ varname }}', ':dummy', {}),
        ]
        self._decorator_tester(tpls4, lib4)


    def test_19_literal(self):

        class CodeBlock(core.Tag):
            options = core.Options(
                arguments.Literal('literal'),
                arguments.EndTag()
            )

            def render_tag(self, context, literal):
                return literal

        tpls = [
            ('{% code_block %}{# comment #}{% endcode_block %}', '{# comment #}', {}),
            ('{% code_block %}{{ variable }}{% endcode_block %}', '{{ variable }}', {}),
            ('{% code_block %}{% tag %}{% endcode_block %}', '{% tag %}', {}),
            ('{% code_block %}Text{% endcode_block %}', 'Text', {}),
            ('{% code_block %}{# comment #}{{ var }}{% tag %}Text{% endcode_block %}', 
             '{# comment #}{{ var }}{% tag %}Text', {}),
        ]
        self._tag_tester(tpls, CodeBlock)


    def test_20_expression(self):

        class Set(core.Tag):
            options = core.Options(
                arguments.Argument("variable", resolve=False),
                arguments.Constant("="),
                arguments.Expression("value")
            )

            def render_tag(self, context, variable, value):
                context[variable] = value
                return ""

        tpls = [
            ('{% set var = value %}{{var}}','2',{"var":1,"value":2}),
            ('{% set var=value %}{{var}}','2',{"var":1,"value":2}),
            ('{% set var = value - 1 %}{{var}}','1',{"var":1,"value":2}),
            ('{% set var = value * value + var %}{{var}}','5',{"var":1,"value":2}),
            ('{% set var = value * (value + var) %}{{var}}','6',{"var":1,"value":2}),
            ('{% set var = value|default:"default" %}{{var}}','default',{"var":1,}),
            ('{% set var = value|default:"default"|upper %}{{var}}','VALUE',{"value":"value"}),
            ('{% set var="https://url.com?key=value" %}{{var}}','https://url.com?key=value',{}),
        ]
        self._tag_tester(tpls, Set)

        lib = template.Library()
        lib.tag(Set.as_tag())
        builtins.append(lib)

        self.assertRaises(template.TemplateSyntaxError, template.Template, "{{ value|spaceout }}")
        self.assertRaises(template.TemplateSyntaxError, template.Template,
                          "{% set var = value|spaceout %}")
        t = template.Template("{% load ct_filter %}{% set var = value|spaceout %}{{var}}")
        c = template.Context({"value":"separate"})
        s = t.render(c)
        self.assertEqual(s, "s e p a r a t e")

        builtins.remove(lib)

    def test_21_chain(self):

        class Echo(core.Tag):
            options = core.Options(arguments.Argument("arg"))
            def render_tag(self, context, arg):
                return arg

        class Field(object):
            def __init__(self, value):
                self.field = value

        class Attr(object):
            def __init__(self, value):
                self._attr = value
            def __getattr__(self, name):
                if name == "attr":
                    return self._attr
                raise AttributeError()

        class Item(object):
            def __init__(self, value):
                self._item = value
            def __getitem__(self, key):
                if key == "item":
                    return self._item
                raise KeyError()

        class Method(object):
            def __init__(self, value):
                self._value = value
            def get(self):
                return self._value

        ## {{ chain.dict.0.field.attr.item.get }}
        chain1 = { "dict": [ Field(Attr(Item(Method("value")))) ] }
        ## {{ chain.0.get.dict.attr.field.item }}
        chain2 = [ { "dict": Method(Attr(Field(Item("value")))) } ] 
        ## {{ chain.get.0.dict.attr.field.item }}
        chain3 = Method([ { "dict": Attr(Field(Item("value"))) } ]) 

        tpls = [
            ('{{ chain.dict.0.field.attr.item.get }}','value',{"chain":chain1}),
            ('{{ chain.0.dict.get.attr.field.item }}','value',{"chain":chain2}),
            ('{{ chain.get.0.dict.attr.field.item }}','value',{"chain":chain3}),
        ]
        self._tag_tester(tpls)

        tpls = [
            ('{% echo chain.dict.0.field.attr.item.get %}','value',{"chain":chain1}),
            ('{% echo chain.0.dict.get.attr.field.item %}','value',{"chain":chain2}),
            ('{% echo chain.get.0.dict.attr.field.item %}','value',{"chain":chain3}),
            ('{% echo chain.dict.0.field.attr.item.get() %}','value',{"chain":chain1}),
            ('{% echo chain.0.dict.get().attr.field.item %}','value',{"chain":chain2}),
            ('{% echo chain.get().0.dict.attr.field.item %}','value',{"chain":chain3}),
        ]
        self._tag_tester(tpls, Echo)
         

    def test_22_commas(self):

        class Concat(core.Tag):
            options = core.Options(arguments.MultiValueArgument("args"))

            def render_tag(self, context, args):
                return "".join([str(arg) for arg in args])

        class ConcatCommas(core.Tag):
            options = core.Options(arguments.MultiValueArgument("args", commas=True))

            def render_tag(self, context, args):
                return "".join([str(arg) for arg in args])

        class With(core.Tag):
            options = core.Options(
                arguments.MultiValueKeywordArgument("arguments"),
                arguments.NodeList("nodelist"),
                arguments.EndTag()
            )
            def render_tag(self, context, arguments, nodelist):
                context.push()
                try:
                    context.update(arguments)
                    return nodelist.render(context)
                finally:
                    context.pop()

        class WithCommas(core.Tag):
            options = core.Options(
                arguments.MultiValueKeywordArgument("arguments", commas=True),
                arguments.NodeList("nodelist"),
                arguments.EndTag()
            )
            def render_tag(self, context, arguments, nodelist):
                context.push()
                try:
                    context.update(arguments)
                    return nodelist.render(context)
                finally:
                    context.pop()

        tpls = [
            ('{% concat "a" "b" "c" d "e" "f" g %}', 'abcdefg' , {"d":"d","g":"g"}),
            ('{% concat num * 3 22 / 2 %}', '9911' , {"num" : 33}),
            ('{% concat d if True else 1 22 / 2 %}', 'd11' , {"d":"d","g":"g"}),
            ('{% concat_commas "a","b","c",d,"e","f",g %}', 'abcdefg' , {"d":"d","g":"g"}),
            ('{% concat_commas num * 3, 22 / 2 %}', '9911' , {"num" : 33}),
            ('{% concat_commas d if True else 1, 22 / 2 %}', 'd11' , {"d":"d","g":"g"}),
            ('{% with a=1 b=6/3 %}{{a}}|{{b}}{% endwith %}', '1|2', {}),
            ('{% with a=1 if False else 2 b=6/3 %}{{a}}|{{b}}{% endwith %}', '2|2', {}),
            ('{% with_commas a=1, b=6/3 %}{{a}}|{{b}}{% endwith_commas %}', '1|2', {}),
            ('{% with_commas a=1 if False else 2, b=6 %}{{a}}|{{b}}{% endwith_commas %}','2|6',{}),
        ]
        self._tag_tester(tpls, Concat, ConcatCommas, With, WithCommas)
        

    def test_23_function_signature(self):

        class Macro(core.Tag):
            options = core.Options(
                arguments.Argument("macroname", resolve=False),
                arguments.Constant("("),
                arguments.MultiValueArgument("arg_names", resolve=False, 
                                             required=False, commas=True),
                arguments.Constant(")"),
                arguments.NodeList("nodelist"),
                arguments.EndTag()
            )

            def render_tag(self, context, macroname, arg_names, nodelist):

                def call_macro(*args):
                    inner_context = template.Context({macroname: call_macro})
                    i = 0
                    for arg_name in arg_names:
                        inner_context[arg_name] = args[i]
                        i += 1
                    return nodelist.render(inner_context)

                context[macroname] = call_macro
                return ""

        class Echo(core.Tag):
            options = core.Options(arguments.Argument("expression"))
        
            def render_tag(self, context, expression):
                 return expression

        tpls = [
            ('{% macro hello() %}Hello!{% endmacro %}{% echo hello() %}','Hello!',{}),
            ('{% macro hello(name) %}Hello {{name}}!{% endmacro %}{% echo hello("Fred") %}',
             'Hello Fred!',{}),
            ('{% macro hello(first, last) %}Hello {{first}} {{last}}!{% endmacro %}'
             '{% echo hello("John", lastname) %}','Hello John Smith!',{"lastname":"Smith"}),
        ]

        self._tag_tester(tpls, Macro, Echo)


    def test_24_child_tags(self):

        class Hello(core.Tag):
            options = core.Options(
                arguments.Argument("name", required=False)
            )

            def render_tag(self, context, name=None):
                return "Hello " + str(self.get_name(name)) + "!"

            def get_name(self, name):
                return name if name is not None else "World"

        class Hola(Hello):
            def render_tag(self, context, name=None):
                return "Hola " + str(self.get_name(name)) + "!"
  
        tpls = [
            ('{% hello %}','Hello World!',{}),
            ('{% hello "Joe" %}','Hello Joe!',{}),
            ('{% hello (2 + 19) * 2 %}','Hello 42!',{}),
            ('{% hello name %}','Hello Josephine!',{"name": "Josephine"}),
            ('{% hola %}','Hola World!',{}),
            ('{% hola "Jose" %}','Hola Jose!',{}),
            ('{% hola (2 + 19) * 2 %}','Hola 42!',{}),
            ('{% hola name %}','Hola Josefina!',{"name": "Josefina"}),
        ]
        self._tag_tester(tpls, Hello, Hola)


    def test_25_one_of(self):

        class Scope(core.Tag):
            options = core.Options(
                arguments.OneOf(
                    arguments.MultiValueKeywordArgument("newcontext", required=True),
                    arguments.Argument("newcontext")
                ),
                arguments.NodeList("nodelist"),
                arguments.EndTag()
            )
            def render_tag(self, context, nodelist, newcontext):
                context.push()
                try:
                    if not isinstance(newcontext, dict):
                        raise TypeError("Scope requires a dictionary.")
                    context.update(newcontext)
                    return nodelist.render(context)
                finally:
                    context.pop()
                    
                
        tpls = [
            ('{% scope num=(1+2+3+4)/5 str="xyz" %}{{num}},{{str}}{% endscope %}','2,xyz',{}),
            ('{% scope {"num":(1+2+3+4)/5,"str":"xyz"} %}{{num}},{{str}}{% endscope %}','2,xyz',{}),
            ('{% scope dict %}{{num}},{{str}}{% endscope %}','2,xyz',
              {"dict":{"num":(1+2+3+4)/5,"str":"xyz"}}),
        ]
        self._tag_tester(tpls, Scope)

        self.assertRaises(exceptions.ArgumentRequiredError, self._tag_tester, 
                          [('{% scope %}{% endscope %}','',{})], Scope)

        ## Testing get_nodes_by_type
        lib = template.Library()
        lib.tag(Scope.as_tag())
        builtins.append(lib)
        for tpl in tpls:
            tmpl = template.Template(tpl[0])
            nodes = tmpl.nodelist.get_nodes_by_type(VariableNode)
            self.assertEqual(len(nodes),2)
        builtins.remove(lib)

        class Scope(core.Tag):
            options = core.Options(
                arguments.OneOf(
                    arguments.MultiValueKeywordArgument("newcontext", required=False),
                    arguments.Argument("newcontext")
                ),
                arguments.NodeList("nodelist"),
                arguments.EndTag()
            )
            def render_tag(self, context, nodelist, newcontext):
                context.push()
                try:
                    if not isinstance(newcontext, dict):
                        raise TypeError("Scope requires a dictionary.")
                    context.update(newcontext)
                    return nodelist.render(context)
                finally:
                    context.pop()
                
        tpls = [
            ('{% scope %}Hello World!{% endscope %}','Hello World!',{}),
        ]
        self._tag_tester(tpls, Scope)


    def test_26_flag_after_arguments(self):

        class TestTag(core.Tag):
            options = core.Options(
                arguments.MultiValueArgument("myargs", required=False),
                arguments.Flag('allowed', true_values=['allowed'], default=False)
            )
            def render_tag(self, context, myargs, allowed):
                if not allowed:
                    return "NOT ALLOWED!"
                else:
                    return ", ".join(str(x) for x in myargs)

        tpls = [
            ("{% test_tag 'one' 'two' 'three' %}", 'NOT ALLOWED!',{}),
            ("{% test_tag 'one' 'two' 'three' allowed %}", 'one, two, three',{}),
            ('{% test_tag one two three allowed %}', '1, 2, 3',{'one':1,'two':2,'three':3}),
        ]
        self._tag_tester(tpls, TestTag)

        class TestTag(core.Tag):
            options = core.Options(
                arguments.MultiValueArgument("myargs", required=False),
                arguments.Optional(
                    arguments.Flag('allowed', true_values=['allowed'], default=False),
                    'with'
                )
            )
            def render_tag(self, context, myargs, allowed):
                if not allowed:
                    return "NOT ALLOWED!"
                else:
                    return ", ".join(str(x) for x in myargs)

        tpls = [
            ("{% test_tag 'one' 'two' 'three' %}", 'NOT ALLOWED!',{}),
            ("{% test_tag 'one' 'two' 'three' with %}", 'NOT ALLOWED!',{}),
            ("{% test_tag 'one' 'two' 'three' allowed with %}", 'one, two, three',{}),
            ('{% test_tag one two allowed with %}', '1, 2',{'one':1,'two':2}),
        ]
        self._tag_tester(tpls, TestTag)

        class TestTag(core.Tag):
            options = core.Options(
                arguments.MultiValueArgument("myargs", required=False),
                arguments.Optional(
                    arguments.Flag('allowed', true_values=['allowed'], false_values=['not']),
                    'with'
                )
            )
            def render_tag(self, context, myargs, allowed):
                if not allowed:
                    return "NOT ALLOWED!"
                else:
                    return ", ".join(str(x) for x in myargs)

        tpls = [
            ("{% test_tag 'one' 'two' 'three' not with %}", 'NOT ALLOWED!',{}),
            ("{% test_tag 'one' 'two' 'three' allowed with %}", 'one, two, three',{}),
            ('{% test_tag one two allowed with %}', '1, 2',{'one':1,'two':2}),
            ('{% test_tag one two not with %}', 'NOT ALLOWED!',{'one':1,'two':2}),
        ]
        self._tag_tester(tpls, TestTag)


    def test_27_bad_names(self):
        self.assertRaises(exceptions.BaseError, arguments.BaseArgument, True)
        self.assertRaises(exceptions.BaseError, arguments.BaseArgument, True, False)


    def test_99_middleware(self):
        """
        This needs to be last because it modifies the global "builtins" store 
        """

        from django.conf import settings
        from django.test.client import Client
        from customtags.decorators import block

        @block
        def hello(context, nodelist, name="world", as_name="message"):
            context.push()
            try:
                context[as_name] = "hello %s" % name
                return nodelist.render(context) 
            finally:
                context.pop()

            return rendered

        INSTALLED_APPS = ('customtags','customtags_tests',)
        MIDDLEWARE_CLASSES = ('customtags.middleware.AddToBuiltinsMiddleware',)

        old_apps = settings.INSTALLED_APPS
        old_middleware = settings.MIDDLEWARE_CLASSES

        settings.INSTALLED_APPS = INSTALLED_APPS
        settings.MIDDLEWARE_CLASSES = MIDDLEWARE_CLASSES  

        c = Client()
        response = c.get("/test/")
        self.assertEqual(response.content, 'hello customtags\n')
        response = c.get("/test2/")
        self.assertEqual(response.content, 'INPUT\n')

        settings.INSTALLED_APPS = old_apps 
        settings.MIDDLEWARE_CLASSES = old_middleware 
