import re

from functools import update_wrapper
from copy import deepcopy
from collections import deque
from django.template import Node, NodeList as DjangoNodeList
from django.core.exceptions import ImproperlyConfigured

from customtags.arguments import NodeList, BlockTag, TagName, Optional
from customtags.parser import structure_arguments
from customtags.utils import get_default_name, Container
from customtags.lexer import Lexer

INDENT = ' '

class classonlymethod(classmethod):
    def __get__(self, instance, owner):
        if instance is not None:
            raise AttributeError("This method is available only on the view class.")
        return super(classonlymethod, self).__get__(instance, owner)


class Options(object):
    """
    Option class holding the arguments of a tag.
    """
    def __init__(self, *args, **kwargs):
        self.initialized = False
        self.arguments = deque(args)
        self.lexer = Lexer()
        
        blocks = []
        for block in kwargs.get('blocks', []):
            if isinstance(block, basestring):
                blocks.append(NodeList(block))
                blocks.append(BlockTag(block))
            else:
                blocks.append(NodeList(block[1]))
                blocks.append(BlockTag(block[0]))

        if len(blocks) > 0:
            self.arguments.append(blocks[0])
            if len(blocks) > 2:
                optionals = blocks[1:-1]
                while optionals:
                    self.arguments.append(Optional(optionals.pop(0), optionals.pop(0)))
            self.arguments.append(blocks[-1])

    def __deepcopy__(self, memo):
        arguments = deepcopy(self.arguments)
        if self.initialized:
            if isinstance(self.arguments[0], basestring) and \
               self.arguments[0] == self.tagname:
                arguments.popleft()
        return Options(*arguments)

    def __arg_repr(self, args, depth):
        indent = INDENT * depth
        retval = ""
        for arg in args:
            if isinstance(arg, basestring):
                retval += indent + arg + "\n"
            elif hasattr(arg, 'arguments') and arg.arguments:
                retval += indent + "<%s(name=%s):\n" % (arg.__class__.__name__, arg.name)
                retval += self.__arg_repr(arg.arguments, depth+1)
                retval += indent + ">\n"
            else:
                retval += indent + arg.__repr__() + "\n"
                #retval += indent + "<%s(name=%s)>\n" % (arg.__class__.__name__, arg.name)
        return retval

    def __repr__(self):
        tagname = self.tagname if hasattr(self, "tagname") else "<undefined>"
        if hasattr(self, 'args') and hasattr(self, 'kwargs'):
            args_kwargs = ", args=%s, kwargs=%s" % \
                (self.args.__repr__(), self.kwargs.__repr__())
        else:
            args_kwargs = ""

        retval = ""
        retval += "<Options(tagname=%s%s):\n" % (tagname, args_kwargs)
        retval += self.__arg_repr(self.arguments, 1)
        retval += ">"
        return retval

    def initialize(self, tagname):
        if not self.initialized:
            self.tagname = tagname
            self.arguments = structure_arguments(self.arguments, self.tagname)

            if len(self.arguments) > 0: 

               if isinstance(self.arguments[0], BlockTag):
                   raise ImproperlyConfigured("The first argument cannot be a BlockTag.")

               elif not isinstance(self.arguments[0], TagName) and \
                    not isinstance(self.arguments[0], basestring):
                   self.arguments.appendleft(tagname)

               elif isinstance(self.arguments[0], basestring) and \
                    self.arguments[0] != tagname:
                   self.arguments.appendleft(tagname)

               elif self.arguments[0] != tagname and self.arguments[0].tagname != tagname:
                   raise ImproperlyConfigured(
                       "Tag name '%s' does not match first argument %s."
                       % (tagname, str(self.arguments[0])) 
                   )
            else:
                self.arguments.appendleft(tagname)

            self.parser = BlockTag(*self.arguments)
            self.initialized = True

    def parse(self, parser, tokens, container):
        """
        Parse template tokens into a dictionary
        """
        if not hasattr(self, "parser") or not self.parser:
            raise ImproperlyConfigured("'initialize(<tagname>)' must be called on an "
                                       "Options object before 'parse()' may be called.")

        stream = self.lexer.tokenize(tokens.contents)
        self.original_string = tokens.contents
        self.parser.parse(parser, stream, container)


class TagMeta(type):
    def __new__(cls, name, bases, attrs):
        tag_name = attrs.get('name', get_default_name(name))
        attrs['name'] = tag_name

        if 'options' in attrs:
            attrs['options'].initialize(tag_name)
        else:
            parents = [base for base in bases if isinstance(base, TagMeta)]
            options = None
            while options == None and len(parents) > 0:
                parent = parents.pop(0)
                if hasattr(parent, 'options'):
                    options = deepcopy(parent.options)
                    options.initialize(tag_name)
            if not isinstance(options, Options):
                raise ImproperlyConfigured(
                    "None of the parents of Tag (%s), nor the "
                    "tag itself have any options specified." % tag_name
                )
            attrs['options'] = options

        ret = super(TagMeta, cls).__new__(cls, name, bases, attrs)
        return ret


class Tag(Node):
    """
    Tag class.
    """
    __metaclass__ = TagMeta
    
    options = Options()
    
    def __init__(self, **kwargs):
        """
        Constructor. Called in the URLconf; can contain helpful extra
        keyword arguments, and other things.
        """
        # Go through keyword arguments, and either save their values to our
        # instance, or raise an error.
        for key, value in kwargs.iteritems():
            setattr(self, key, value)

    @classonlymethod
    def as_tag(cls, **initkwargs):
        """
        Manner in which to generate a tag function that can be registered.
        """
        if not cls.options.initialized:
            cls.options.initialize(self.name)

        def tag(parser, tokens):
            self = cls(**initkwargs)
            self.tagname = self.name
            self.container = Container()
            self.options.parse(parser, tokens, self.container)
            return self

        update_wrapper(tag, cls)
        tag.__name__ = cls.name
        return tag

    @property
    def nodelist(self):
        return DjangoNodeList(node for nodelist in self.container.tag_nodelists for node in nodelist)
            
    def render(self, context):
        """
        INTERNAL method to prepare rendering
        """
        args   = [v.resolve(context) for v in self.container.tag_args]
        kwargs = dict([(k, v.resolve(context)) for k,v in self.container.tag_kwargs.items()])
   
        return self.render_tag(context, *args, **kwargs)
        
    def render_tag(self, context, *args, **kwargs):
        """
        The method you should override in your custom tags
        """
        raise NotImplementedError
        
    def __repr__(self):
        return '<%s: %s: (%s)>' % (self.__class__.__name__, self.name, self.options)


