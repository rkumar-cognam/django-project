
from django.template import Library
register = Library()

@register.filter
def spaceout(arg):
    return " ".join(str(arg))
