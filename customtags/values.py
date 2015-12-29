import warnings

from django import template
from django.template import VariableDoesNotExist
from django.conf import settings

from customtags.exceptions import TemplateSyntaxWarning


class StaticValue(object):
    """
    A 'constant' internal template variable which basically allows 'resolving'
    returning it's initial value
    """
    def __init__(self, value):
        if isinstance(value, basestring):
            self.value = value.strip('"\'')
        else:
            self.value = value

    def __repr__(self): # pragma: no cover
        return '<StaticValue: %s>' % repr(self.value)

    def resolve(self, context):
        try:
            return self.value
        except VariableDoesNotExist:
            return None


class NullValue(object):
    def __repr__(self):
        return 'NullValue()'

    def resolve(self, context):
        return None


class StringValue(object):
    errors = {}
    value_on_error = ""
    
    def __init__(self, var):
        self.var = var

    def __repr__(self):
        return "<%s(%s)>" % (self.__class__.__name__, self.var.__repr__())
        
    def resolve(self, context):
        try:
            resolved = self.var.resolve(context)
            return self.clean(resolved)
        except VariableDoesNotExist:
            return None
    
    def clean(self, value):
        """
        In the case that the specified string is a static (i.e. explicitly specified) 
        value, then do not change it to None.  In any other case, we have to transform
        the empty string to None because the django template engine transforms None
        to the empty string inside resolve().
        """
        if value == "" and not isinstance(self.var, StaticValue):
            return None
        return value
    
    def error(self, value, category):
        message = self.errors.get(category, "") % {'value': repr(value)}
        if settings.DEBUG:
            raise template.TemplateSyntaxError(message)
        else:
            warnings.warn(message, TemplateSyntaxWarning)
            return self.value_on_error


class IntegerValue(StringValue):
    errors = {
        "clean": "%(value)s could not be converted to Integer",
    }
    
    def clean(self, value):
        if value == "":
            return None
        try:
            return int(value)
        except ValueError:
            return self.error(value, "clean")


class ListValue(list, StringValue):
    """
    A list of template variables for easy resolving
    """
    def __init__(self, value=None):
        list.__init__(self)
        if value is not None:
            self.append(value)
        
    def resolve(self, context):
        try:
            resolved = [item.resolve(context) for item in self]
            return self.clean(resolved)
        except VariableDoesNotExist:
            return None


class DictValue(dict, StringValue):
    """
    A dict of template variables for easy resolving
    """
    def __init__(self, key=None, value=None):
        dict.__init__(self)
        if key is not None and value is not None:
            self[key] = value

    def resolve(self, context):
        try:
            resolved = [(key, self[key].resolve(context)) for key in self]
            return self.clean(dict(resolved))
        except VariableDoesNotExist:
            return None



