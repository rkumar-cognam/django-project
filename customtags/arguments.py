
from collections import deque
from copy import copy

from django.template import TemplateSyntaxError
from django.template.base import TOKEN_BLOCK, TOKEN_TEXT, TOKEN_VAR, TOKEN_COMMENT
from django.template.base import Parser as DjangoParser, NodeList as template_NodeList
from django.core.exceptions import ImproperlyConfigured

from customtags.exceptions import *
from customtags.values import *
from customtags.utils import FakeParser, NULL, Container
from customtags.lexer import Lexer
from customtags.expr_parser import ExprParser

TOKEN_TYPE_DICT = {
  TOKEN_BLOCK : "block",
  TOKEN_TEXT : "text",
  TOKEN_VAR : "variable",
  TOKEN_COMMENT : "comment",
}


class BaseArgument(object):
    def __init__(self, name, required=True):
        self.name = name
        self.required = required
        self.lexer = Lexer()
        self.expr_parser = ExprParser(argument=self)

    def __repr__(self):
        tpl = "<%s(name=%s): %s>"
        tag = "tagname=%s" % self.tagname if hasattr(self, "tagname") \
                                           and self.tagname \
                                          else ""
                                              
        return tpl % (self.__class__.__name__, self.name, tag)

    def initialize(self, tagname):
        self.tagname = tagname
        self.expr_parser.tagname = tagname

    def set_name(self, name):
        if not isinstance(name, basestring) and name is not None:
            raise BaseError("An argument name must be a string, not %s." % name.__repr__())
        self._name = name

    def get_name(self):
        return self._name

    name = property(get_name, set_name)
        
    def clean_token(self, parser, stream):
        msg = "%s doesn't accept a token stream." % self.__class__.__name__
        raise ImproperlyConfigured(msg)

    def parse(self, parser, stream, container, nextargs=None):
        raise NotImplementedError


class TagName(BaseArgument):
    pass


class Constant(BaseArgument):
    def __init__(self, value, required=True):
        self.value = value
        super(Constant, self).__init__(None, required)

    def __repr__(self): # pragma: no cover
        return '<%s: value=%s>' % (self.__class__.__name__, self.value)

    def clean_token(self, parser, stream):
        if stream.eos:
            raise TooFewArguments(str(self), self.tagname)

        if self.value == stream.current.value:
            return stream.current.value
        else:
            raise BreakpointExpected(self.tagname, 
                                     breakpoints=[self.value], 
                                     got=stream.current.value)

    def parse(self, parser, stream, container, nextargs=None):

        self.clean_token(parser, stream)
        next(stream)
        

class Argument(BaseArgument):
    """
    A basic single value argument.
    """
    value_class = StringValue 
    
    def __init__(self, name=None, default=None, required=True, 
                 resolve=True, exclude=None):
        self.exclude = list(exclude) if exclude is not None else []
        self.default = default
        self.resolve = resolve
        super(Argument, self).__init__(name, required)
        
    def get_default(self):
        """
        Get the default value
        """
        return StaticValue(self.default)

    def clean_token(self, parser, stream):
        current = stream.current
        if stream.eos:
            raise ArgumentRequiredError(self, self.tagname)
        if current.value in self.exclude:
            raise InvalidArgument(self, current.value, self.tagname)

        try:
            if self.resolve:
                return self.expr_parser.parse(stream, parser)
            else:
                result = StaticValue(current.value)
                next(stream)
                return result
        except TemplateSyntaxError, e:
            raise
        except Warning, w:
            raise
        except Exception, e:
            raise TemplateSyntaxError("Argument unable to process token '%s'." % current.value)

    def get_value(self, parser, stream, nextargs=None):
        name, value = self.name, self.clean_token(parser, stream)
        return name, self.value_class(value)

    def set_value(self, name, value, container):
        if name is not None:
            if name in container.tag_kwargs:
                raise KeywordInUse(name, self.tagname)

            container.tag_kwargs[str(name)] = value

        elif isinstance(value, (list, tuple)):
            [args.append(item) for item in value]

        else:
            container.tag_args.append(value)

    def parse(self, parser, stream, container, nextargs=None):

        name, value = self.get_value(parser, stream, nextargs)
        self.set_value(name, value, container)


class KeywordArgument(Argument):

    def clean_token(self, parser, stream):
        currrent = stream.current
        if stream.eos:
            raise ArgumentRequiredError(self, self.tagname)

        try:
            name = stream.expect("name").value
            stream.expect("assign")
            value = self.expr_parser.parse(stream, parser)
        except Exception, e:
            raise
            #raise FormatError(self.__class__.__name__, 'keyword=<value expression>')
        
        if name in self.exclude:
            raise InvalidArgument(self, value, self.tagname)

        self.validate_name(name)

        return name, value

    def validate_name(self, name):
        if self.name and name != self.name:
            raise ArgumentRequiredError(self, self.tagname)
            
    def get_value(self, parser, stream, nextargs=None):
        name, value = self.clean_token(parser, stream)
        return name, self.value_class(value)
            

class IntegerArgument(Argument):
    """
    Same as Argument but converts the value to integers.
    """
    value_class = IntegerValue 


class IntegerKeywordArgument(KeywordArgument):
    """
    Same as Argument but converts the value to integers.
    """
    value_class = IntegerValue 
    
    
class MultiValueBase(object):
    """
    An argument which allows multiple values.

    This type of argument is different than a Repetition in the way that it decides
    to terminate the repetition.  A Repetition moves forward in the parsing until the
    point that the pattern no longer matches.  If there is any ambiguity, it favors
    what is in the loop.

    A subclass of MultiValueBase will consume tokens until it encounters a set of tokens
    that might be consumed by subsiquent arguments.  In order to perform this lookahead,
    it calls clean_token() on those parsers to determine if they can handle the tokens 
    in the stream.

    Currently this is only written to handle multiple arguments or keyword arguments.
    """
    
    def __init__(self, name=None, default=NULL, required=False, max_values=None,
                 resolve=True, commas=False):
        self.max_values = max_values
        self.commas = commas
        self.values = None

        if default is NULL:
            default = []
        super(MultiValueBase, self).__init__(name, default, required, resolve)

    def _do_parse(self, parser, stream, container, nextargs=None):
        num = 0

        current = stream.current
        if stream.eos:
            return num
        if nextargs is None:
            nextargs = []
        
        len_nextargs = len(nextargs)
        i = 0

        
        max_values = stream.size if self.max_values is None else self.max_values
        check_commas = False
        while not stream.eos and i < max_values:
            j = 0
            while j < len_nextargs:
                try:
                    # This is because the other try statement below takes care
                    # of the first non-optional argument after the multi-value arg
                    if not isinstance(nextargs[j], Optional):
                        break
                    nextargs[j].clean_token(parser, copy(stream))
                    return num
                except BaseError:
                    pass
                j += 1

            try:
                if j < len_nextargs and not isinstance(nextargs[j], Optional):
                    nextargs[j].clean_token(parser, copy(stream))
                    return num
            except BaseError:
                pass

            if check_commas:
                try:
                    stream.expect("comma")
                except BaseError:
                    break

            name, value = self.get_value(parser, stream)
            self.set_value(name, value, container)
            num += 1
            i += 1

            if self.commas:
                check_commas = True

        return num


class MultiValueArgument(MultiValueBase, Argument):
    sequence_class = ListValue

    def set_value(self, name, value, container):
        if self.name:
            if self.name not in container.tag_kwargs:
                container.tag_kwargs[str(self.name)] = self.sequence_class()
            elif not isinstance(container.tag_kwargs[self.name], self.sequence_class):
                raise KeywordInUse(self.name, self.tagname)
            container.tag_kwargs[self.name].append(value)
        else:
            container.tag_args.append(value)

    def parse(self, parser, stream, container, nextargs=None):

        num = self._do_parse(parser, stream, container, nextargs) 
        if num == 0:
            if self.required:
                raise TooFewArguments(str(self), self.tagname)
            elif self.name:
                if self.name not in container.tag_kwargs:
                    container.tag_kwargs[str(self.name)] = self.sequence_class()
                elif not isinstance(container.tag_kwargs[self.name], self.sequence_class):
                    raise KeywordInUse(self.name, self.tagname)
        

class MultiValueKeywordArgument(MultiValueBase, KeywordArgument):
    sequence_class = DictValue

    def set_value(self, name, value, container):
        if self.name:
            if self.name not in container.tag_kwargs:
                container.tag_kwargs[str(self.name)] = self.sequence_class()
            elif not isinstance(container.tag_kwargs[self.name], self.sequence_class):
                raise KeywordInUse(self.name, self.tagname)
            elif name in container.tag_kwargs[self.name]:
                raise KeywordInUse(name, self.tagname)
            container.tag_kwargs[self.name][name] = value

        else:
            if name in container.tag_kwargs:
                raise KeywordInUse(name, self.tagname)

            container.tag_kwargs[str(name)] = value

    def validate_name(self, name):
        pass
            
    def parse(self, parser, stream, container, nextargs=None):
        num = self._do_parse(parser, stream, container, nextargs) 
        if num == 0:
            if self.required:
                raise TooFewArguments(str(self), self.tagname)
            elif self.name:
                if self.name not in container.tag_kwargs:
                    container.tag_kwargs[str(self.name)] = self.sequence_class()
                elif not isinstance(container.tag_kwargs[self.name], self.sequence_class):
                    raise KeywordInUse(self.name, self.tagname)


class Flag(Argument):
    """
    A boolean flag
    """
    def __init__(self, name=None, default=NULL, true_values=None, false_values=None,
                 case_sensitive=False):
        if default is not NULL:
            required = False
        else:
            required = True
        super(Flag, self).__init__(name, default, required)

        if true_values is None:
            true_values = []
        if false_values is None:
            false_values = []
        if case_sensitive:
            self.mod = lambda x: x
        else:
            self.mod = lambda x: str(x).lower()

        self.true_values = [self.mod(tv) for tv in true_values]
        self.false_values = [self.mod(fv) for fv in false_values]
        if not any([self.true_values, self.false_values]):
            raise ImproperlyConfigured(
                "Flag must specify either true_values and/or false_values"
            )

    def clean_token(self, parser, stream):
        """
        Determine if the leftmost token is a valid value
        """
        if stream.eos:
            raise TooFewArguments(str(self), self.tagname)
        token = stream.current.value
        ltoken = self.mod(token)

        if token in self.exclude or ltoken in self.exclude:
            raise InvalidArgument(self, token, self.tagname)
        
        if self.true_values and ltoken in self.true_values:
            return StaticValue(True)

        elif self.false_values and ltoken in self.false_values:
            return StaticValue(False)

        allowed_values = []
        if self.true_values:
            allowed_values += self.true_values
        if self.false_values:
            allowed_values += self.false_values
        raise InvalidFlag(self.name, token, allowed_values, self.tagname)

    def parse(self, parser, stream, container, nextargs=None):
        try:
            value = self.clean_token(parser, stream)
            next(stream)
        except InvalidFlag, e:
            if self.default is NULL:
                raise
            value = self.get_default()

        self.set_value(self.name, value, container)


class Expression(Argument):
    pass


class NodeList(BaseArgument):

    def __init__(self, name=None, endtags=None, required=True):
        self.explicit_endtags = endtags
        self.endtags = endtags
        super(NodeList, self).__init__(name, required)

    def __repr__(self):
        return "<%s: %s/%s>" % (self.__class__.__name__, self.name, repr(self.endtags))

    def get_default(self):
        return StaticValue(template_NodeList())

    def clean_token(self, parser, stream, container=None):
        if not stream.eos:
            raise TooManyArguments(str(self), [token.value for token in stream.list])

    def parse(self, parser, stream, container, nextargs=None):
        self.clean_token(parser, stream)

        nodelist = parser.parse(self.endtags)
        wrapped_nodelist = StaticValue(nodelist)
        if self.name is None:
            container.tag_args.append(wrapped_nodelist)
        else:
            container.tag_kwargs[str(self.name)] = wrapped_nodelist
        container.tag_nodelists.append(nodelist)


class Literal(NodeList):

    def get_default(self):
        return StaticValue("")

    def parse(self, parser, stream, container, nextargs=None):
        self.clean_token(parser, stream)

        literal = ''.join({
            TOKEN_BLOCK: '{%% %s %%}',
            TOKEN_VAR: '{{ %s }}',
            TOKEN_COMMENT: '{# %s #}',
            TOKEN_TEXT: '%s',
        }[token.token_type] % token.contents for token in self._do_parse(parser))

        if self.name is None:
            container.tag_args.append(StaticValue(literal))
        else:
            container.tag_kwargs[str(self.name)] = StaticValue(literal)

    def _do_parse(self, parser):
        """
        Parse to the end of a literal block. This is different than Parser.parse()
        in that it does not generate Node objects; it simply yields tokens.
        """
        depth = 0
        while parser.tokens:
            token = parser.tokens[0]
            if token.token_type == TOKEN_BLOCK:
                if token.contents == self.name:
                    depth += 1
                elif token.contents in self.endtags or \
                     token.contents == self.endtags:
                    depth -= 1
            if depth < 0:
                break
            yield parser.next_token()
        if not parser.tokens and depth >= 0:
            parser.unclosed_block_tag(self.endtags)


class MultiArgument(BaseArgument):
    def __init__(self, *args, **kwargs):
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            self.arguments = list(args[0])
        else:
            self.arguments = list(args)
        
        name = kwargs.pop('name', None)
        required = kwargs.get("required", True)
        super(MultiArgument, self).__init__(name, required)

    def __repr__(self):
        tpl = "<%s%s: %s>"
        opt = ", ".join(x.__repr__() for x in self.arguments)
        tag = "(tagname:%s)" % self.tagname if hasattr(self, "tagname") \
                                           and self.tagname \
                                          else ""
                                              
        return tpl % (self.__class__.__name__, tag, opt)

    def clean_token(self, parser, stream):
        stream_copy = copy(stream)
        arguments = deque(self.arguments)
        while not stream_copy.eos and arguments:
            current_arg = arguments.popleft()
            current_arg.clean_token(parser, stream_copy)
            next(stream_copy)
        # if the stream has run out, the next arg must be a NodeList
        if arguments:
            assert stream_copy.eos
            current_arg = arguments.popleft()
            current_arg.clean_token(parser, stream_copy)
       
    def _do_parse(self, parser, stream, container, nextargs=None):
        arguments = deque(self.arguments)

        current_arg = None
        while arguments:
            current_arg = arguments.popleft()
            nextargs_arguments = nextargs if len(arguments) == 0 else list(arguments)
            current_arg.parse(parser, stream, container, nextargs_arguments)

    def parse(self, parser, stream, container, nextargs=None):
        self._do_parse(parser, stream, container, nextargs)
        

class OneOf(MultiArgument):

    def __repr__(self):
        tpl = "<%s%s: %s>"
        opt = ", ".join(x.__repr__() for x in self.arguments)
        tag = "(tagname:%s)" % self.tagname if hasattr(self, "tagname") \
                                           and self.tagname \
                                          else ""
                                              
        return tpl % (self.__class__.__name__, tag, opt)

    def clean_token(self, parser, stream):
        is_accepted = False
        for argument in self.arguments:
            stream_copy = copy(stream)
            try:
                argument.clean_token(parser, stream_copy)
                is_accepted = True
                break
            except:
                pass
        if not is_accepted:
            raise BaseError(message="None of the specified options match.")

    def parse(self, parser, stream, container, nextargs=None):
        arguments = deque(self.arguments)

        current_arg = None
        while arguments:
            current_arg = arguments.popleft()

            stream_copy = copy(stream)
            if hasattr(parser, 'tokens'):
                parser_copy = DjangoParser(list(parser.tokens))
                parser_copy.tags    = copy(parser.tags)
                parser_copy.filters = copy(parser.filters)
            else:
                parser_copy = FakeParser(parser)

            try:
                current_arg.parse(parser_copy, stream_copy, Container(), nextargs)
            except BaseError, e:
                pass
            except Exception, e:
                raise
            else:
                current_arg.parse(parser, stream, container, nextargs)
                return

        raise ArgumentRequiredError(self, self.tagname)


class BlockTag(MultiArgument):

    def __init__(self, name=None, *args, **kwargs):

        if name is None:
            self.tagname = name
        elif isinstance(name, basestring):
            self.tagname = name
        elif isinstance(name, TagName):
            self.tagname = name.name
        else:
            raise ImproperlyConfigured(
                "The first argument of BlockTag must be a string or a TagName obj, "
                "or another BlockTag object, not %s." % name
            )
        self.lexer = Lexer()

        kwargs['name'] = self.tagname
        super(BlockTag, self).__init__(*args, **kwargs)

    def initialize(self, tagname):
        super(BlockTag, self).initialize(self.tagname)

    def clean_token(self, parser, stream):
        if self.tagname is not None and not stream.eos:

            token = stream.current.value
            while stream.look().type == "dot":
                next(stream)
                next(stream)
                token = stream.current.value
            if token != self.tagname:
                raise TagNameError(token, self.tagname)

    def parse(self, parser, stream, container, nextargs=None):
        if stream.eos:
            block_found = False
            while (not block_found):
                parser_token = parser.next_token()
                stream = self.lexer.tokenize(parser_token.contents)
                if parser_token.token_type == TOKEN_BLOCK:
                    if stream.current.type == "name" and stream.current.value == "comment":
                        parser.parse(("endcomment",))
                        parser.next_token() 
                    else:
                        block_found = True
                elif parser_token.token_type == TOKEN_VAR:
                    raise UnexpectedElement(TOKEN_TYPE_DICT[parser_token.type], tokens[0])

        if self.tagname is not None:
            self.clean_token(parser, stream)
            next(stream)
        
        self._do_parse(parser, stream, container, nextargs)
        if not stream.eos:
            raise TooManyArguments(str(self), [token.value for token in stream.list])


class Optional(MultiArgument):

    def parse(self, parser, stream, container, nextargs=None):
        stream_copy = copy(stream)
        if hasattr(parser, 'tokens'):
            parser_copy = DjangoParser(list(parser.tokens))
            parser_copy.tags    = copy(parser.tags)
            parser_copy.filters = copy(parser.filters)
        else:
            parser_copy = FakeParser(parser)

        try:
            self._do_parse(parser_copy, stream_copy, Container(), nextargs)
        except BaseError, e:
            pass
        except Exception, e:
            raise
        else:
            self._do_parse(parser, stream, container, nextargs)
            return
        
        for option in self.arguments:
            try:
                if hasattr(option, 'get_default'):
                    if option.name is None:
                        container.tag_args.append(option.get_default())
                    else:
                        container.tag_kwargs[str(option.name)] = option.get_default() 
            except NotImplementedException:
                pass


class RepContainer(object):
    def __init__(self):
        self.tag_args = ListValue()
        self.tag_kwargs = DictValue()
        self.tag_nodelists = []
        self._resolved = False

    def resolve(self, context):
        self._resolved = True
        self.args = self.tag_args.resolve(context)
        self.kwargs = self.tag_kwargs.resolve(context)
        return self

    def __getitem__(self, key):
        if not self._resolved:
            raise ImproperlyConfigured('RepContainer must be resolved before accessing items.')
        if isinstance(key, basestring):
            return self.kwargs[key]
        if isinstance(key, int):
            return self.args[key]
        raise KeyError("Invalid key to access Repetition values: '%s'." % key)


class Repetition(Optional):
    def __init__(self, name=None, *args, **kwargs):
        self.min_reps = kwargs.pop("min_reps", 0) 
        self.max_reps = kwargs.pop("max_reps", None) 
        if self.min_reps and self.min_reps > 0:
            kwargs['required'] = True
        else:
            kwargs['required'] = False 

        kwargs['name'] = name
        super(Optional, self).__init__(*args, **kwargs)

    def parse(self, parser, stream, container, nextargs=None):
        stream_copy = copy(stream)
        if hasattr(parser, 'tokens'):
            parser_copy = DjangoParser(list(parser.tokens))
            parser_copy.tags    = copy(parser.tags)
            parser_copy.filters = copy(parser.filters)
        else:
            parser_copy = FakeParser(parser)

        reps = ListValue() 
        add_reps = True
        while (add_reps):
            try:
                self._do_parse(parser_copy, stream_copy, Container(), nextargs)
            except BaseError, e:
                add_reps = False
            except Exception, e:
                raise
            else:
                rep_container = RepContainer()
                self._do_parse(parser, stream, rep_container, nextargs)
                reps.append(rep_container)
                container.tag_nodelists.extend(rep_container.tag_nodelists)

        if len(reps) < self.min_reps:
            raise ArgumentRequiredError(self, self.tagname)

        if self.max_reps and len(reps) > self.max_reps:
            raise TooManyArguments(str(self), list(tokens))

        if not reps:
            rep_container = RepContainer()
            has_defaults = False

            for option in self.arguments:
                try:
                    if hasattr(option, 'get_default'):
                        has_defaults = True
                        if option.name is None:
                            rep_container.tag_args.append(option.get_default())
                        else:
                            rep_container.tag_kwargs[str(option.name)] = option.get_default() 
                except NotImplementedException:
                    pass

            if has_defaults:
                reps.append(rep_container)

        if self.name is None:
            container.tag_args.append(reps)
        else:
            container.tag_kwargs[self.name] = reps


class EndTag(BaseArgument):
    def __init__(self, name=None, *args, **kwargs):
        self.init_name = name
        self.otherargs = args

        required = kwargs.get("required", True)
        super(EndTag, self).__init__(name, required)

    def initialize(self, tagname):
        if self.init_name:
            self.tagname = self.init_name
        else:
            self.tagname = 'end' + tagname
        if not self.name:
            self.name = self.tagname

    def clean_token(self, parser, stream):
        if not stream.eos:
            raise TooManyArguments(str(self), [token.value for token in stream.list])

    def parse(self, parser, tokens, container, nextargs=None):

        block_found = False
        while (not block_found):
            parser_token = parser.next_token()
            tokens = deque(parser_token.split_contents())
            if parser_token.token_type == TOKEN_BLOCK:
                if tokens[0] == "comment":
                    parser.parse(("endcomment",))
                    parser.next_token()
                else:
                    block_found = True
            elif parser_token.token_type == TOKEN_VAR:
                raise UnexpectedElement(TOKEN_TYPE_DICT[parser_token.type], tokens[0])

        tokens = deque(parser_token.split_contents())

        if tokens.popleft() != self.tagname:
            raise ArgumentRequiredError(self, self.tagname)

        if len(tokens) != 0:
            raise TooManyArguments(str(self), list(tokens))


###
### These methods strip the Optional containers from lists of arguments.
###

def next_contained_first(argument_list):
    for first_arg in next_contained_argument(argument_list, True):
        yield first_arg

def next_contained_argument(argument_list, firsts_only=False):
    top_args = list(argument_list)
    while len(top_args) > 0:
        current_arg = top_args.pop(0)
        if isinstance(current_arg, Optional):
            for inner_arg in next_contained_argument(current_arg.arguments, firsts_only):
                yield inner_arg
        else:
            yield current_arg
            if firsts_only:
                break

