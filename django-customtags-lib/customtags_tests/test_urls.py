try:
    from django.conf.urls import patterns
except ImportError, e:
    from django.conf.urls.defaults import patterns
from django.views.generic.base import TemplateView

class ContextView(TemplateView):
    extra_context = {}
    def get_context_data(self, *args, **kwargs):
        context = super(ContextView, self).get_context_data(*args, **kwargs)
        context.update(self.extra_context)
        return context


urlpatterns = patterns('',
    (r'^test/', TemplateView.as_view(template_name='test_hello.html')),
    (r'^test2', ContextView.as_view(template_name='test_with.html',
                                    extra_context={'input':'input'})),
)

