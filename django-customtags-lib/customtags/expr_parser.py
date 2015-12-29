"""
    customtags.expr_parser
    ~~~~~~~~~~~~~

    Implements the template parser.

    :copyright: (c) 2010 by the Jinja Team.
    :copyright: (c) 2015 by legutierr
    :license: BSD, see LICENSE for more details.
"""
import warnings

try:
    from django.utils.deprecation import RemovedInDjango110Warning as DjangoDeprecationWarning
except ImportError:
    DjangoDeprecationWarning = DeprecationWarning 

from django.template import TemplateSyntaxError
from customtags import nodes
from customtags.tokens import describe_token, describe_token_expr
from customtags._compat import next, imap


#: statements that callinto 
_statement_keywords = frozenset(['for', 'if', 'block', 'extends', 'print',
                                 'macro', 'include', 'from', 'import',
                                 'set'])
_compare_operators = frozenset(['eq', 'ne', 'lt', 'lteq', 'gt', 'gteq'])


class ExprParser(object):
    """This is the central parsing class Jinja2 uses.  It's passed to
    extensions and can be used to parse expressions or statements.
    """

    def __init__(self, argument=None, tag_name=''):
        self.extensions = {}
        self.argument = argument
        self._last_identifier = 0
        self._tag_stack = []
        self._end_token_stack = []

    def fail(self, msg, lineno=None, exc=TemplateSyntaxError):
        """Convenience method that raises `exc` with the message, passed
        line number or last line number as well as the current name.
        """
        if lineno is None:
            lineno = self.stream.current.lineno
        tagname = getattr(self.argument, 'tagname', '<unknown tag>')
        raise exc(msg, lineno, tagname)

    def is_tuple_end(self, extra_end_rules=None):
        """Are we at the end of a tuple?"""
        if self.stream.current.type in ('variable_end', 'block_end', 'rparen'):
            return True
        elif extra_end_rules is not None:
            return self.stream.current.test_any(extra_end_rules)
        return False

    def parse(self, stream, django_parser):
        self.stream = stream
        self.django_parser = django_parser
        return self.parse_expression(True)

    def parse_expression(self, with_condexpr=True):
        """Parse an expression.  Per default all expressions are parsed, if
        the optional `with_condexpr` parameter is set to `False` conditional
        expressions are not parsed.
        """
        if with_condexpr:
            return self.parse_condexpr()
        return self.parse_or()

    def parse_condexpr(self):
        expr1 = self.parse_or()
        while self.stream.skip_if('name:if'):
            expr2 = self.parse_or()
            if self.stream.skip_if('name:else'):
                expr3 = self.parse_condexpr()
            else:
                expr3 = None
            expr1 = nodes.CondExpr(expr2, expr1, expr3)
        return expr1

    def parse_or(self):
        left = self.parse_and()
        while self.stream.skip_if('name:or'):
            right = self.parse_and()
            left = nodes.Or(left, right)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.stream.skip_if('name:and'):
            right = self.parse_not()
            left = nodes.And(left, right)
        return left

    def parse_not(self):
        if self.stream.current.test('name:not'):
            next(self.stream)
            return nodes.Not(self.parse_not())
        return self.parse_compare()

    def parse_compare(self):
        expr = self.parse_add()
        ops = []
        while 1:
            token_type = self.stream.current.type
            if token_type == 'assign':
                token_type = 'eq'
                warnings.warn(
                    "Operator '=' is deprecated and will be removed in Django 1.10. "
                    "Use '==' instead.",
                    DjangoDeprecationWarning, stacklevel=2
                )

            if token_type in _compare_operators:
                next(self.stream)
                ops.append(nodes.Operand(token_type, self.parse_add()))
            elif self.stream.skip_if('name:in'):
                ops.append(nodes.Operand('in', self.parse_add()))
            elif self.stream.current.test('name:not') and \
                 self.stream.look().test('name:in'):
                self.stream.skip(2)
                ops.append(nodes.Operand('notin', self.parse_add()))
            else:
                break
        if not ops:
            return expr
        return nodes.Compare(expr, ops)

    def parse_add(self):
        left = self.parse_sub()
        while self.stream.current.type == 'add':
            next(self.stream)
            right = self.parse_sub()
            left = nodes.Add(left, right)
        return left

    def parse_sub(self):
        left = self.parse_concat()
        while self.stream.current.type == 'sub':
            next(self.stream)
            right = self.parse_concat()
            left = nodes.Sub(left, right)
        return left

    def parse_concat(self):
        args = [self.parse_mul()]
        while self.stream.current.type == 'tilde':
            next(self.stream)
            args.append(self.parse_mul())
        if len(args) == 1:
            return args[0]
        return nodes.Concat(args)

    def parse_mul(self):
        left = self.parse_div()
        while self.stream.current.type == 'mul':
            next(self.stream)
            right = self.parse_div()
            left = nodes.Mul(left, right)
        return left

    def parse_div(self):
        left = self.parse_floordiv()
        while self.stream.current.type == 'div':
            next(self.stream)
            right = self.parse_floordiv()
            left = nodes.Div(left, right)
        return left

    def parse_floordiv(self):
        left = self.parse_mod()
        while self.stream.current.type == 'floordiv':
            next(self.stream)
            right = self.parse_mod()
            left = nodes.FloorDiv(left, right)
        return left

    def parse_mod(self):
        left = self.parse_pow()
        while self.stream.current.type == 'mod':
            next(self.stream)
            right = self.parse_pow()
            left = nodes.Mod(left, right)
        return left

    def parse_pow(self):
        left = self.parse_unary()
        while self.stream.current.type == 'pow':
            next(self.stream)
            right = self.parse_unary()
            left = nodes.Pow(left, right)
        return left

    def parse_unary(self, with_filter=True):
        token_type = self.stream.current.type
        if token_type == 'sub':
            next(self.stream)
            node = nodes.Neg(self.parse_unary(False))
        elif token_type == 'add':
            next(self.stream)
            node = nodes.Pos(self.parse_unary(False))
        else:
            node = self.parse_primary()
        node = self.parse_postfix(node)
        if with_filter:
            node = self.parse_filter_expr(node)
        return node

    def parse_primary(self):
        token = self.stream.current
        if token.type == 'name':
            if token.value in ('true', 'false', 'True', 'False'):
                node = nodes.Const(token.value in ('true', 'True'))
            elif token.value in ('none', 'None'):
                node = nodes.Const(None)
            else:
                node = nodes.Name(token.value)
            next(self.stream)
        elif token.type == 'string':
            next(self.stream)
            node = nodes.Const(token.value)
        elif token.type in ('integer', 'float'):
            next(self.stream)
            node = nodes.Const(token.value)
        elif token.type == 'lparen':
            next(self.stream)
            node = self.parse_tuple(explicit_parentheses=True)
            self.stream.expect('rparen')
        elif token.type == 'lbracket':
            node = self.parse_list()
        elif token.type == 'lbrace':
            node = self.parse_dict()
        else:
            self.fail("unexpected '%s'" % describe_token(token))
        return node

    def parse_tuple(self, simplified=False, with_condexpr=True,
                    extra_end_rules=None, explicit_parentheses=False):
        """Works like `parse_expression` but if multiple expressions are
        delimited by a comma a :class:`~customtags.nodes.Tuple` node is created.
        This method could also return a regular expression instead of a tuple
        if no commas where found.

        The default parsing mode is a full tuple.  If `simplified` is `True`
        only names and literals are parsed.  The `no_condexpr` parameter is
        forwarded to :meth:`parse_expression`.

        Because tuples do not require delimiters and may end in a bogus comma
        an extra hint is needed that marks the end of a tuple.  For example
        for loops support tuples between `for` and `in`.  In that case the
        `extra_end_rules` is set to ``['name:in']``.

        `explicit_parentheses` is true if the parsing was triggered by an
        expression in parentheses.  This is used to figure out if an empty
        tuple is a valid expression or not.
        """
        if simplified:
            parse = self.parse_primary
        elif with_condexpr:
            parse = self.parse_expression
        else:
            parse = lambda: self.parse_expression(with_condexpr=False)
        args = []
        is_tuple = False
        while 1:
            if args:
                self.stream.expect('comma')
            if self.is_tuple_end(extra_end_rules):
                break
            args.append(parse())
            if self.stream.current.type == 'comma':
                is_tuple = True
            else:
                break

        if not is_tuple:
            if args:
                return args[0]

            # if we don't have explicit parentheses, an empty tuple is
            # not a valid expression.  This would mean nothing (literally
            # nothing) in the spot of an expression would be an empty
            # tuple.
            if not explicit_parentheses:
                self.fail('Expected an expression, got \'%s\'' %
                          describe_token(self.stream.current))

        return nodes.Tuple(args)

    def parse_list(self):
        token = self.stream.expect('lbracket')
        items = []
        while self.stream.current.type != 'rbracket':
            if items:
                self.stream.expect('comma')
            if self.stream.current.type == 'rbracket':
                break
            items.append(self.parse_expression())
        self.stream.expect('rbracket')
        return nodes.List(items)

    def parse_dict(self):
        token = self.stream.expect('lbrace')
        items = []
        while self.stream.current.type != 'rbrace':
            if items:
                self.stream.expect('comma')
            if self.stream.current.type == 'rbrace':
                break
            key = self.parse_expression()
            self.stream.expect('colon')
            value = self.parse_expression()
            items.append(nodes.Pair(key, value))
        self.stream.expect('rbrace')
        return nodes.Dict(items)

    def parse_postfix(self, node):
        while 1:
            token_type = self.stream.current.type
            if token_type == 'dot' or token_type == 'lbracket':
                node = self.parse_subscript(node)
            # calls are valid both after postfix expressions (getattr
            # and getitem) as well as filters and tests
            elif token_type == 'lparen':
                node = self.parse_call(node)
            else:
                break
        return node

    def parse_filter_expr(self, node):
        while 1:
            token_type = self.stream.current.type
            if token_type == 'pipe':
                node = self.parse_filter(node)
            elif token_type == 'name' and self.stream.current.value == 'is':
                node = self.parse_test(node)
            # calls are valid both after postfix expressions (getattr
            # and getitem) as well as filters and tests
            elif token_type == 'lparen':
                node = self.parse_call(node)
            else:
                break
        return node

    def parse_subscript(self, node):
        token = next(self.stream)
        if token.type == 'dot':
            attr_token = self.stream.current
            next(self.stream)
            if attr_token.type == 'name':
                return nodes.Getattr(node, attr_token.value)
            elif attr_token.type != 'integer':
                self.fail('expected name or number', attr_token.lineno)
            arg = nodes.Const(attr_token.value)
            return nodes.Getitem(node, arg)
        if token.type == 'lbracket':
            args = []
            while self.stream.current.type != 'rbracket':
                if args:
                    self.stream.expect('comma')
                args.append(self.parse_subscribed())
            self.stream.expect('rbracket')
            if len(args) == 1:
                arg = args[0]
            else:
                arg = nodes.Tuple(args)
            return nodes.Getitem(node, arg)
        self.fail('expected subscript expression', self.lineno)

    def parse_subscribed(self):

        if self.stream.current.type == 'colon':
            next(self.stream)
            args = [None]
        else:
            node = self.parse_expression()
            if self.stream.current.type != 'colon':
                return node
            next(self.stream)
            args = [node]

        if self.stream.current.type == 'colon':
            args.append(None)
        elif self.stream.current.type not in ('rbracket', 'comma'):
            args.append(self.parse_expression())
        else:
            args.append(None)

        if self.stream.current.type == 'colon':
            next(self.stream)
            if self.stream.current.type not in ('rbracket', 'comma'):
                args.append(self.parse_expression())
            else:
                args.append(None)
        else:
            args.append(None)

        return nodes.Slice(*args)

    def parse_call(self, node):

        token = self.stream.expect('lparen')
        args = []
        kwargs = []
        dyn_args = dyn_kwargs = None
        require_comma = False

        def ensure(expr):
            if not expr:
                self.fail('invalid syntax for function call expression',
                          token.lineno)

        while self.stream.current.type != 'rparen':
            if require_comma:
                self.stream.expect('comma')
                # support for trailing comma
                if self.stream.current.type == 'rparen':
                    break
            if self.stream.current.type == 'mul':
                ensure(dyn_args is None and dyn_kwargs is None)
                next(self.stream)
                dyn_args = self.parse_expression()
            elif self.stream.current.type == 'pow':
                ensure(dyn_kwargs is None)
                next(self.stream)
                dyn_kwargs = self.parse_expression()
            else:
                ensure(dyn_args is None and dyn_kwargs is None)
                if self.stream.current.type == 'name' and \
                    self.stream.look().type == 'assign':
                    key = self.stream.current.value
                    self.stream.skip(2)
                    value = self.parse_expression()
                    kwargs.append(nodes.Keyword(key, value))
                else:
                    ensure(not kwargs)
                    args.append(self.parse_expression())

            require_comma = True
        self.stream.expect('rparen')

        if node is None:
            return args, kwargs, dyn_args, dyn_kwargs
        return nodes.Call(node, args, kwargs, dyn_args, dyn_kwargs)

    def parse_filter(self, node, start_inline=False):
        while self.stream.current.type == 'pipe' or start_inline:
            if not start_inline:
                next(self.stream)
            token = self.stream.expect('name')
            name = token.value
            while self.stream.current.type == 'dot':
                next(self.stream)
                name += '.' + self.stream.expect('name').value
            if self.stream.current.type == 'lparen':
                args, kwargs, dyn_args, dyn_kwargs = self.parse_call(None)
            elif self.stream.current.type == 'colon':
                next(self.stream)
                # this can't just be parsed as an expression because there would
                # be ambiguity with regards to the application of filters down the chain
                args = [self.parse_unary(with_filter=False)]
                kwargs = []
                dyn_args = dyn_kwargs = None
            else:
                args = []
                kwargs = []
                dyn_args = dyn_kwargs = None
            filter_func = self.django_parser.find_filter(name)
            node = nodes.Filter(node, filter_func, name, args, kwargs, dyn_args, dyn_kwargs)
            start_inline = False
        return node

    def parse_test(self, node):
        token = next(self.stream)
        if self.stream.current.test('name:not'):
            next(self.stream)
            negated = True
        else:
            negated = False
        name = self.stream.expect('name').value
        while self.stream.current.type == 'dot':
            next(self.stream)
            name += '.' + self.stream.expect('name').value
        dyn_args = dyn_kwargs = None
        kwargs = []
        if self.stream.current.type == 'lparen':
            args, kwargs, dyn_args, dyn_kwargs = self.parse_call(None)
        elif self.stream.current.type in ('name', 'string', 'integer',
                                          'float', 'lparen', 'lbracket',
                                          'lbrace') and not \
             self.stream.current.test_any('name:else', 'name:or',
                                          'name:and'):
            if self.stream.current.test('name:is'):
                self.fail('You cannot chain multiple tests with is')
            args = [self.parse_expression()]
        else:
            args = []
        node = nodes.Test(node, name, args, kwargs, dyn_args, dyn_kwargs)
        if negated:
            node = nodes.Not(node)
        return node

