
from functools import update_wrapper
from django import template
from customtags.templatetags.customtags import register
from customtags.arguments import *
from customtags.core import *
from customtags.utils import process_decorator_args_kwargs



class TagFactory(object):
   
    @staticmethod 
    def get_class(options, callback, name=None):
        name = name if name is not None else callback.__name__

        def render_tag(self, context, *args, **kwargs):
            return callback(context, *args, **kwargs)

        options = Options(*options) if not isinstance(options, Options) else options
        tag_class = type(name, (Tag,), { 'options':options, 'render_tag':render_tag })
        tag_class.__module__ = callback.__module__
        return tag_class


def block_decorator(register=register, name=None):
    assert isinstance(name, basestring) or name is None 
    assert isinstance(register, template.Library)

    outer_name = name
    outer_register = register

    def decorator(*args, **kwargs):
        kwargs = process_decorator_args_kwargs(Options, *args, **kwargs)
        if 'options' in kwargs:
            raise TypeError(
                "Options cannot be passed into the block decorator."
            )

        register = outer_register if 'register' not in kwargs else kwargs['register']
        name = outer_name if 'name' not in kwargs else kwargs['name']

        if 'function' not in kwargs:
            return block_decorator(register, name)

        function = kwargs['function']
        def callback(context, *args, **kwargs):
            nodelist = kwargs.pop("__nodelist__")
            as_name = kwargs.pop("__as_name__")
            if as_name is not None:
                kwargs['as_name'] = as_name
            return function(context, nodelist, *args, **kwargs)

        update_wrapper(callback, function)
        callback.__module__ = function.__module__

        options = [MultiValueArgument(), 
                   MultiValueKeywordArgument(), 
                   Optional(Constant("as"), Argument("__as_name__", resolve=False)),
                   NodeList("__nodelist__"),
                   EndTag()]

        tag_class = TagFactory.get_class(options, callback, name)
        register.tag(tag_class.as_tag())

        return tag_class
    return decorator 

block = block_decorator()


def function_decorator(register=register, name=None):
    assert isinstance(name, basestring) or name is None 
    assert isinstance(register, template.Library)

    outer_name = name
    outer_register = register

    def decorator(*args, **kwargs):
        kwargs = process_decorator_args_kwargs(Options, *args, **kwargs)
        if 'options' in kwargs:
            raise TypeError(
                "Options cannot be passed into the block decorator."
            )

        register = outer_register if 'register' not in kwargs else kwargs['register']
        name = outer_name if 'name' not in kwargs else kwargs['name']

        if 'function' not in kwargs:
            return function_decorator(register, name)

        function = kwargs['function']
        def callback(context, *args, **kwargs):
            as_name = kwargs.pop("__as_name__")
            result = function(context, *args, **kwargs)
            if as_name is not None:
                context[as_name] = result
                return ""
            else:
                return result

        update_wrapper(callback, function)
        callback.__module__ = function.__module__

        options = [MultiValueArgument(), 
                   MultiValueKeywordArgument(), 
                   Optional(Constant("as"), Argument("__as_name__", resolve=False))]

        tag_class = TagFactory.get_class(options, callback, name)
        register.tag(tag_class.as_tag())

        return tag_class
    return decorator 

function = function_decorator()

