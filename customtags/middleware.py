import os

from types import ModuleType
from importlib import import_module
from django.template.base import add_to_builtins, builtins, InvalidTemplateLibrary
from django.conf import settings

registry = set()

TAGS_USE_NAMESPACE = getattr(settings, 'TAGS_USE_NAMESPACE', True)

class AddToBuiltinsMiddleware(object):
    """
    This Middleware class reads through the templatetags module of each INSTALLED_APP, 
    looking for any Library instances that may be defined directly inside each submodule
    thereof. It then attaches those instances to the template.builtins list. All of this
    is only done once; a list of each of the modules is kept in a registry, and each
    module in that registry is never loaded after the first time.
    """

    def process_request(self, request):

        for app in settings.INSTALLED_APPS:
            if app not in registry:
                registry.add(app)
                try:
                    mod = import_module('%s.templatetags' % app)
                    files = os.listdir(os.path.dirname(mod.__file__))

                    for module in [file[:-3] for file in files if file[-3:] == '.py']:
                        try:
                            add_to_builtins('%s.templatetags.%s' % (app, module))

                            if TAGS_USE_NAMESPACE:
                                lib = builtins[-1]

                                for key in lib.tags.keys():
                                    namespaced_key = "%s.%s" % (app, key)
                                    lib.tags[namespaced_key] = lib.tags[key]

                                for key in lib.filters.keys():
                                    namespaced_key = "%s.%s" % (app, key)
                                    lib.filters[namespaced_key] = lib.filters[key]

                        except InvalidTemplateLibrary, e:
                            pass
                except ImportError, e:
                    pass

