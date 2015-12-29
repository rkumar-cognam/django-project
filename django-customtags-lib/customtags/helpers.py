from django.template.loader import render_to_string
from django.core.exceptions import ImproperlyConfigured

from customtags.core import Tag
from customtags.arguments import Argument, Constant, NodeList, next_contained_argument


class AsTag(Tag):
    """
    Same as tag but allows for an optional 'as varname'. The 'as varname'
    options must be added 'manually' to the options class.
    """

    def __init__(self, **initkwargs):
        second_to_last = None
        last = None
        node_or_empty = None
        for argument in next_contained_argument(self.options.arguments):
            second_to_last = last
            last = node_or_empty
            node_or_empty = argument
            if isinstance(node_or_empty, NodeList):
                break
        if not isinstance(node_or_empty, NodeList):
            second_to_last = last
            last = node_or_empty
            node_or_empty = None

        if second_to_last != "as" and \
           (not isinstance(second_to_last, Constant) or second_to_last.value != "as"):
            raise ImproperlyConfigured(
                "AsTag subclasses require that an 'as' keyword be specified ."
            )
        if not isinstance(last, Argument): 
            raise ImproperlyConfigured(
                "The argument that follows the 'as' keyword must be of type Argument."
            )
        elif last.resolve:
            raise ImproperlyConfigured(
                "The Argument object that follows the 'as' keyword must not be resolved."
            )
        self.varname_name = last.name
        super(AsTag, self).__init__(**initkwargs)
    
    def render_tag(self, context, *args, **kwargs):
        varname = kwargs.pop(self.varname_name)
        value = self.get_value(context, *args, **kwargs)
        if varname:
            context[varname] = value
            return ''
        return value
    
    def get_value(self, context, *args, **kwargs):
        raise NotImplementedError
    
    
class InclusionTag(Tag):
    template = None
    
    def __init__(self, **initkwargs):
        super(InclusionTag, self).__init__(**initkwargs)
        if self.template is None:
            raise ImproperlyConfigured(
                "InclusionTag subclasses require the template attribute to be "
                "set."
            )
    
    def render_tag(self, context, **kwargs):
        template = self.get_template(context, **kwargs)
        data = self.get_context(context, **kwargs)
        return render_to_string(template, data)
    
    def get_template(self, context, **kwargs):
        return self.template
    
    def get_context(self, context, **kwargs):
        return {}


