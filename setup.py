from distutils.core import setup, Extension

module1 = Extension('maxminddb',
                    libraries=['maxminddb'],
                    sources=['maxminddb.c'],
                    extra_compile_args=['-Wall', '-Werror', '-Wextra'],
                    )

setup(name='MaxMind DB Reader',
      version='1.0.0',
      description='This is a python wrapper to libmaxminddb',
      ext_modules=[module1])
