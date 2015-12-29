from setuptools import setup, find_packages

version = __import__('customtags').__version__

setup(
    name = 'django-customtags-lib',
    version = version,
    description = 'Class based template tags for Django',
    author = 'Luis Gutierrez-Sheris',
    url = 'http://github.com/legutierr/django-customtags-lib/',
    packages = find_packages(),
    zip_safe=False,
)
