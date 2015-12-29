import re
from django import template

class NULL:
    """
    Internal type to differentiate between None and No-Input
    """

_re1 = re.compile('(.)([A-Z][a-z]+)')
_re2 = re.compile('([a-z0-9])([A-Z])')

def get_default_name(name):
    """
    Turns "CamelCase" into "camel_case"
    """
    return _re2.sub(r'\1_\2', _re1.sub(r'\1_\2', name)).lower()
 

class FakeParser(object):
    """
    This is basically here to clear classytags' tests, which treat integers as
    acceptible tokens, although they would never appear in any parsed result.

    If an actual dango parser were cloned and used, it would fail the tests because
    integer input is invalid.

    TODO: Remove this, and modify the tests.
    """

    def __init__(self, parser):
        self.parser = parser

    def compile_filter(self, *args, **kwargs):
        self.parser.compile_filter(*args, **kwargs)

    def next_token(self, *args, **kwargs):
        raise NotImplementedException

    def parse(self, *args, **kwargs):
        raise NotImplementedException


class Container(object):
    def __init__(self, tag_args=None, tag_kwargs=None, tag_nodelists=None):
        self.tag_args = [] if not tag_args else tag_args
        self.tag_kwargs = {} if not tag_kwargs else tag_kwargs
        self.tag_nodelists = [] if not tag_nodelists else tag_nodelists

    def __repr__(self):
        return "Container(tag_args=%s, tag_kwargs=%s, tag_nodelists=%s)" % (self.tag_args, self.tag_kwargs, self.tag_nodelists)
 

def process_decorator_args_kwargs(options_class, *args, **kwargs):
    has_options = False
    has_register = False
    has_function = False
    has_name = False

    for arg in args:
        if isinstance(arg, basestring):
            if has_name:
                raise TypeError(
                    "More than one name has been passed to the decorator.  Please only "
                    "specify a single string, if you provide any."
                )
            has_name = True
            name = arg
        elif isinstance(arg, template.Library):
            if has_register:
                raise TypeError(
                    "More than one register Library object has been passed to the "
                    "decorator. Please only specify a single register Libarary object."
                )
            has_register = True
            register = arg
        elif callable(arg):
            if has_function:
                raise TypeError(
                    "More than one callable or function has been passed to the decorator. "
                    "Please only specify a single callable or function."
                )
            has_function = True
            function = arg
        elif isinstance(arg, options_class):
            if has_options:
                raise TypeError(
                    "More than one options list has been passed to the decorator. "
                    "Please only specify a single options list."
                )
            has_options = True
            options = new_options
        else:
            # this approach allows options to be passed in as any iterable
            try:
                args = [x for x in arg]
            except:
                raise TypeError(
                    "Unknown arg '%s' passed to the decorator." % arg.__repr__()
                )
            new_options = options_class(*args)
            if has_options:
                raise TypeError(
                    "More than one options list has been passed to the decorator. "
                    "Please only specify a single options list."
                )
            has_options = True
            options = new_options

    if "name" in kwargs and isinstance(kwargs['name'], basestring):
        if has_name:
            raise TypeError(
                "More than one name has been passed to the decorator.  Please only "
                "specify a single name string, if you provide any."
            )
        has_name = True
        name = kwargs.pop("name")
    if "register" in kwargs and isinstance(kwargs['register'], template.Library):
        if has_register:
            raise TypeError(
                "More than one register Library object has been passed to the "
                "decorator. Please only specify a single register Libarary object."
            )
        has_register = True
        register = kwargs.pop("register")
    if "options" in kwargs: 
        if isinstance(kwargs['options'], options_class):
            if has_options:
                raise TypeError(
                    "More than one options list has been passed to the decorator. "
                    "Please only specify a single options list."
                )
            has_options = True
            options = new_options
        else:
            try:
                args = [x for x in arg]
            except:
                raise TypeError(
                    "Unknown arg '%s' passed to the decorator." % arg.__repr__()
                )
            new_options = options_class(*args)
            if has_options:
                raise TypeError(
                    "More than one options list has been passed to the decorator. "
                    "Please only specify a single options list."
                )
            has_options = True
            options = new_options

    if len(kwargs) > 0:
        raise TypeError("Unknown keyword '%s' passed to the decorator." % kwargs.keys()[0])

    result = {}
    if has_name:
        result['name'] = name
    if has_register:
        result['register'] = register 
    if has_function:
        result['function'] = function
    if has_options:
        result['options'] = options

    return result
