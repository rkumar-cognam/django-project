# -*- coding: utf-8 -*-
"""
    customtags.nodes
    ~~~~~~~~~~~~

    This module implements additional nodes derived from the ast base node.

    It also provides some node tree helper functions like `in_lineno` and
    `get_nodes` used by the parser and translator in order to normalize
    python and jinja nodes.

    :copyright: (c) 2010 by the Jinja Team.
    :license: BSD, see LICENSE for more details.
"""
import operator

from collections import deque
from django.utils.translation import ugettext as _
from django.template.base import Variable, VariableDoesNotExist 
from django.template.context import BaseContext

from customtags.exceptions import BaseError
from customtags._compat import next, izip, with_metaclass, text_type, \
     method_type, function_type


## TODO: I think we only need _cmpop_to_func here
_binop_to_func = {
    '*':        operator.mul,
    '/':        operator.truediv,
    '//':       operator.floordiv,
    '**':       operator.pow,
    '%':        operator.mod,
    '+':        operator.add,
    '-':        operator.sub
}

_uaop_to_func = {
    'not':      operator.not_,
    '+':        operator.pos,
    '-':        operator.neg
}

_cmpop_to_func = {
    'eq':       operator.eq,
    'ne':       operator.ne,
    'gt':       operator.gt,
    'gteq':     operator.ge,
    'lt':       operator.lt,
    'lteq':     operator.le,
    'in':       lambda a, b: a in b,
    'notin':    lambda a, b: a not in b
}

_allop_to_func = {}
_allop_to_func.update(_binop_to_func)
_allop_to_func.update(_uaop_to_func)
_allop_to_func.update(_cmpop_to_func)


class NodeType(type):
    """A metaclass for nodes that handles the field and attribute
    inheritance.  fields and attributes from the parent class are
    automatically forwarded to the child."""

    def __new__(cls, name, bases, d):
        for attr in 'fields', 'attributes':
            storage = []
            storage.extend(getattr(bases[0], attr, ()))
            storage.extend(d.get(attr, ()))
            assert len(bases) == 1, 'multiple inheritance not allowed'
            assert len(storage) == len(set(storage)), 'layout conflict'
            d[attr] = tuple(storage)
        d.setdefault('abstract', False)
        return type.__new__(cls, name, bases, d)


class Node(with_metaclass(NodeType, object)):
    """Baseclass for all Jinja2 nodes.  There are a number of nodes available
    of different types.  There are two major types:

    -   :class:`Expr`: expressions
    -   :class:`Helper`: helper nodes

    All nodes have fields.  Fields may be other nodes, lists, or arbitrary values.  
    Fields are passed to the constructor as regular positional arguments.
    """
    fields = ()
    abstract = True

    def __init__(self, *fields):
        if self.abstract:
            raise TypeError('abstract nodes are not instanciable')
        if fields:
            if len(fields) != len(self.fields):
                if not self.fields:
                    raise TypeError('%r takes 0 arguments' %
                                    self.__class__.__name__)
                raise TypeError('%r takes 0 or %d argument%s' % (
                    self.__class__.__name__,
                    len(self.fields),
                    len(self.fields) != 1 and 's' or ''
                ))
            for name, arg in izip(self.fields, fields):
                setattr(self, name, arg)

    def __eq__(self, other):
        return type(self) is type(other) and \
               tuple(self.iter_fields()) == tuple(other.iter_fields())

    def __ne__(self, other):
        return not self.__eq__(other)

    # Restore Python 2 hashing behavior on Python 3
    __hash__ = object.__hash__

    def __repr__(self):
        return '%s(%s)' % (
            self.__class__.__name__,
            ', '.join('%s=%r' % (arg, getattr(self, arg, None)) for
                      arg in self.fields)
        )


class Helper(Node):
    """Nodes that exist in a specific context only."""
    abstract = True


class Expr(Node):
    """Baseclass for all expressions."""
    abstract = True

    def can_assign(self):
        """Check if it's possible to assign something to this node."""
        return False

    def resolve_safe(self, context):
        try:
            return self.resolve(context)
        except VariableDoesNotExist, e:
            return None


class BinExpr(Expr):
    """Baseclass for all binary expressions."""
    fields = ('left', 'right')
    operator = None
    abstract = True


class UnaryExpr(Expr):
    """Baseclass for all unary expressions."""
    fields = ('node',)
    operator = None
    abstract = True


class Name(Expr):
    """Looks up a name."""
    fields = ('name',)

    def __init__(self, *args, **kwargs):
        super(Name, self).__init__(*args, **kwargs)
        if self.name in ('and', 'or'):
            raise BaseError('"%s" is a reserved keyword and cannot be used as a name '
                            'for a variable or a function.' % self.name)

    def resolve(self, context, call_callable=True):

        if self.name in ('none', 'None'): return None
        if self.name in ('true', 'True'): return True
        if self.name in ('false', 'False'): return False
        if self.name == "_": return _
        
        return resolve_lookup(self.name, context, call_callable)


class Literal(Expr):
    """Baseclass for literals."""
    abstract = True


class Const(Literal):
    """All constant values.  The parser will return this node for simple
    constants such as ``42`` or ``"foo"`` but it can be used to store more
    complex values such as lists too.  Only constants with a safe
    representation (objects where ``eval(repr(x)) == x`` is true).
    """
    fields = ('value',)

    def resolve(self, context):
        return self.value


class TemplateData(Literal):
    """A constant template string."""
    fields = ('data',)

    def resolve(self, context):
        return self.data


class Tuple(Literal):
    """For loop unpacking and some other things like multiple arguments
    for subscripts.  Like for :class:`Name` `ctx` specifies if the tuple
    is used for loading the names or storing.
    """
    fields = ('items')

    def resolve(self, context):
        resolved_list = []
        for item in self.items:
            try:
                resolved_list.append(item.resolve(context))
            except VariableDoesNotExist, e:
                resolved_list.append("")
        return tuple(resolved_list)


class List(Literal):
    """Any list literal such as ``[1, 2, 3]``"""
    fields = ('items',)

    def resolve(self, context):
        resolved_list = []
        for item in self.items:
            try:
                resolved_list.append(item.resolve(context))
            except VariableDoesNotExist, e:
                resolved_list.append("")
        return resolved_list


class Dict(Literal):
    """Any dict literal such as ``{1: 2, 3: 4}``.  The items must be a list of
    :class:`Pair` nodes.
    """
    fields = ('items',)

    def resolve(self, context):
        resolved_dict = {}
        for pair in self.items:
            resolved_pair = pair.resolve(context)
            resolved_dict[resolved_pair[0]] = resolved_pair[1]
        return resolved_dict


class Pair(Helper):
    """A key, value pair for dicts."""
    fields = ('key', 'value')

    def resolve(self, context):
        try:
            key = self.key.resolve(context)
        except VariableDoesNotExist, e:
            raise NameError("Cannot resolve key with variable name '%s'" % self.key.name)
        try:
            value = self.value.resolve(context)
        except VariableDoesNotExist, e:
            value = ""
        return (key, value)


class Keyword(Helper):
    """A key, value pair for keyword arguments where key is a string."""
    fields = ('key', 'value')

    def resolve(self, context):
        try:
            value = self.value.resolve(context)
        except VariableDoesNotExist, e:
            value = ""
        return (self.key, value)


class CondExpr(Expr):
    """A conditional expression (inline if expression).  (``{{
    foo if bar else baz }}``)
    """
    fields = ('test', 'expr1', 'expr2')

    def resolve(self, context):
        test = self.test.resolve(context)
        expr1 = self.expr1.resolve(context)
        expr2 = self.expr2.resolve(context)
        return expr1 if test else expr2


class Filter(Expr):
    """This node applies a filter on an expression.  `name` is the name of
    the filter, the rest of the fields are the same as for :class:`Call`.

    If the `node` of a filter is `None` the contents of the last buffer are
    filtered.  Buffers are created by macros and filter blocks.
    """
    fields = ('node', 'filter_func', 'name', 'args', 'kwargs', 'dyn_args', 'dyn_kwargs')

    def resolve(self, context):
        node = self.node.resolve_safe(context)
        args = [arg.resolve(context) for arg in self.args]
        kwargs = [kwarg.resolve(context) for kwarg in self.kwargs]

        if self.dyn_args:
            args = args + self.dyn_args.resolve(context)
        if self.dyn_kwargs:
            kwargs = kwargs + self.dyn_kwargs.resolve(context)

        return self.filter_func(node, *args, **dict(kwargs))


class Test(Expr):
    """Applies a test on an expression.  `name` is the name of the test, the
    rest of the fields are the same as for :class:`Call`.
    """
    fields = ('node', 'name', 'args', 'kwargs', 'dyn_args', 'dyn_kwargs')

    def resolve(self, context):
        import pdb; pdb.set_trace()


class Call(Expr):
    """Calls an expression.  `args` is a list of arguments, `kwargs` a list
    of keyword arguments (list of :class:`Keyword` nodes), and `dyn_args`
    and `dyn_kwargs` has to be either `None` or a node that is used as
    node for dynamic positional (``*args``) or keyword (``**kwargs``)
    arguments.
    """
    fields = ('node', 'args', 'kwargs', 'dyn_args', 'dyn_kwargs')

    def resolve(self, context):
        try:
            func = self.node.resolve(context, call_callable=False)
        except VariableDoesNotExist, e:
            raise NameError("Function name '%s' is not defined." % self.node.name)
        if not hasattr(func, "__call__"):
            raise NameError("Object with name '%s' is not callable." % self.node.name)

        args = []
        for arg in self.args:
            try:
                args.append(arg.resolve(context))
            except Exception, e:
                args.append("")

        kwargs = dict([kwarg.resolve(context) for kwarg in self.kwargs])

        if self.dyn_args:
            try:
                args.extend(self.dyn_args.resolve(context))
            except Exception, e:
                name = self.dyn_args.name
                raise ValueError("Dynamic args '%s' must not be undefined." % name)
        if self.dyn_kwargs:
            try:
                kwargs.update(self.dyn_kwargs.resolve(context))
            except Exception, e:
                name = self.dyn_kwargs.name
                raise ValueError("Dynamic kwargs '%s' must not be undefined." % name)

        return func(*args, **kwargs)


class Getitem(Expr):
    """Get an attribute or item from an expression and prefer the item."""
    fields = ('node', 'arg')

    def can_assign(self):
        ## TODO: introduce item assignment functionality
        return False

    def resolve(self, context, call_callable=True):
        if isinstance(self.arg, basestring):
            key = self.arg
        elif hasattr(self.arg, 'resolve'):
            key = self.arg.resolve(context)
        else:
            raise TypeError("The 'arg' field must be a string or a node with a resolve method.")

        store = self.node.resolve(context)
        return resolve_lookup(key, store, call_callable)


class Getattr(Expr):
    """Get an attribute or item from an expression that is a ascii-only
    bytestring and prefer the attribute.
    TODO: in django, this should probably be the same as Getitem
    """
    fields = ('node', 'attr')

    def can_assign(self):
        ## TODO: introduce attribute assignment functionality
        return False

    def resolve(self, context, call_callable=True):
        if isinstance(self.attr, basestring):
            key = self.attr
        elif hasattr(self.attr, 'resolve'):
            key = self.attr.resolve(context)
        else:
            raise TypeError("The 'attr' field must be a string or a node with a resolve method.")

        store = self.node.resolve(context)
        return resolve_lookup(key, store, call_callable)


class Slice(Expr):
    """Represents a slice object.  This must only be used as argument for
    :class:`Subscript`.
    """
    fields = ('start', 'stop', 'step')

    def resolve(self, context):
        start = self.start.resolve(context)
        stop = self.stop.resolve(context)
        step = self.step.resolve(context)
        return (start, stop, step)


class Concat(Expr):
    """Concatenates the list of expressions provided after converting them to
    unicode.
    """
    fields = ('nodes',)

    def resolve(self, context):
        return u"".join(unicode(node.resolve(context)) for node in self.nodes)


class Compare(Expr):
    """Compares an expression with some other expressions.  `ops` must be a
    list of :class:`Operand`\s.
    """
    fields = ('expr', 'ops')

    def resolve(self, context):
        curr_expr = self.expr.resolve_safe(context)

        ops = (op.resolve(context) for op in self.ops)
        for op, expr in ops:
            curr_expr = _cmpop_to_func[op](curr_expr, expr)
        return curr_expr


class Operand(Helper):
    """Holds an operator and an expression."""
    fields = ('op', 'expr')

    def resolve(self, context):
        return (self.op, self.expr.resolve_safe(context))

if __debug__:
    Operand.__doc__ += '\nThe following operators are available: ' + \
        ', '.join(sorted('``%s``' % x for x in _allop_to_func))


class Mul(BinExpr):
    """Multiplies the left with the right node."""
    operator = '*'

    def resolve(self, context):
        return self.left.resolve(context) * self.right.resolve(context)


class Div(BinExpr):
    """Divides the left by the right node."""
    operator = '/'

    def resolve(self, context):
        return self.left.resolve(context) / self.right.resolve(context)


class FloorDiv(BinExpr):
    """Divides the left by the right node and truncates conver the
    result into an integer by truncating.
    """
    operator = '//'

    def resolve(self, context):
        return self.left.resolve(context) // self.right.resolve(context)


class Add(BinExpr):
    """Add the left to the right node."""
    operator = '+'

    def resolve(self, context):
        left = self.left.resolve(context)
        right = self.right.resolve(context)
        return left + right


class Sub(BinExpr):
    """Substract the right from the left node."""
    operator = '-'

    def resolve(self, context):
        left = self.left.resolve(context)
        right = self.right.resolve(context)
        return left - right


class Mod(BinExpr):
    """Left modulo right."""
    operator = '%'

    def resolve(self, context):
        return self.left.resolve(context) % self.right.resolve(context)


class Pow(BinExpr):
    """Left to the power of right."""
    operator = '**'

    def resolve(self, context):
        return self.left.resolve(context) ** self.right.resolve(context)


class And(BinExpr):
    """Short circuited AND."""
    operator = 'and'

    def resolve(self, context):
        return self.left.resolve_safe(context) and self.right.resolve_safe(context)


class Or(BinExpr):
    """Short circuited OR."""
    operator = 'or'

    def resolve(self, context):
        return self.left.resolve_safe(context) or self.right.resolve_safe(context)


class Not(UnaryExpr):
    """Negate the expression."""
    operator = 'not'

    def resolve(self, context):
        return not self.node.resolve_safe(context)


class Neg(UnaryExpr):
    """Make the expression negative."""
    operator = '-'

    def resolve(self, context):
        return -self.node.resolve(context)


class Pos(UnaryExpr):
    """Make the expression positive (noop for most expressions)"""
    operator = '+'

    def resolve(self, context):
        return +self.node.resolve(context)


def resolve_lookup(key, store, call_callable=True):
    """
    Performs resolution of a real variable (i.e. not a literal) against the
    given context.

    As indicated by the method's name, this method is an implementation
    detail and shouldn't be called by external code. Use Variable.resolve()
    instead.
    """
    try:  # catch-all for silent variable failures

        try:  # dictionary lookup
            value = store[key]
            # ValueError/IndexError are for numpy.array lookup on
            # numpy < 1.9 and 1.9+ respectively
        except (TypeError, AttributeError, KeyError, ValueError, IndexError):

            try:  # attribute lookup
                # Don't return class attributes if the class is the context:
                if isinstance(store, BaseContext) and getattr(type(store), key):
                    raise AttributeError
                value = getattr(store, key)

            except (TypeError, AttributeError) as e:
                # Reraise an AttributeError raised by a @property
                if (isinstance(e, AttributeError) and
                        not isinstance(store, BaseContext) and key in dir(store)):
                    raise
                try:  # list-index lookup
                    value = store[int(key)]
                except (IndexError,  # list index out of range
                        ValueError,  # invalid literal for int()
                        KeyError,    # current is a dict without `int(bit)` key
                        TypeError):  # unsubscriptable object
                    raise VariableDoesNotExist("Failed lookup for key [%s] in %r",
                                               (key, store))  # missing attribute

        if callable(value):
            if getattr(value, 'alters_data', False):
                raise AttributeError("Must not access callable where "
                                     "alters_data == True")

            elif getattr(value, 'do_not_call_in_templates', False):
                raise AttributeError("Must not access callable where "
                                     "do_not_call_in_templates == True")

            if call_callable:
                value = value()

    except Exception as e:
        if getattr(e, 'silent_variable_failure', False):
            raise VariableDoesNotExist("Silent variable failure for key [%s] in %r.", (key, store))
        else:
            raise

    return value

