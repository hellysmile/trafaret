# -*- coding: utf-8 -*-

import sys
import functools
import inspect
import re
import copy
import itertools
import numbers


# Python3 support
py3 = sys.version_info[0] == 3
if py3:
    import urllib.parse as urlparse
    str_types = (str, bytes)
    unicode = str
else:
    from future_builtins import map
    import urlparse
    str_types = (str, unicode)


"""
Trafaret is tiny library for data validation
It provides several primitives to validate complex data structures
Look at doctests for usage examples
"""

__all__ = ("DataError", "Trafaret", "Any", "Int", "String",
           "List", "Dict", "Or", "Null", "Float", "Enum", "Callable"
           "Call", "Forward", "Bool", "Type", "Mapping", "guard", )


def py3metafix(cls):
    if not py3:
        return cls
    else:
        newcls = cls.__metaclass__(cls.__name__, (cls,), {})
        newcls.__doc__ = cls.__doc__
        return newcls


class DataError(ValueError):

    """
    Error with data preserve
    error can be a message or None if error raised in childs
    data can be anything
    """

    def __init__(self, error=None, name=None):
        self.error = error
        self.name = name

    def __str__(self):
        return str(self.error)

    def __repr__(self):
        return 'DataError(%s)' % str(self)

    def as_dict(self):
        def as_dict(dataerror):
            if not isinstance(dataerror.error, dict):
                return self.error
            return dict((k, v.as_dict() if isinstance(v, DataError) else v)
                        for k, v in dataerror.error.items())
        return as_dict(self)


class TrafaretMeta(type):

    """
    Metaclass for trafarets to make using "|" operator possible not only
    on instances but on classes

    >>> Int | String
    <Or(<Int>, <String>)>
    >>> Int | String | Null
    <Or(<Int>, <String>, <Null>)>
    >>> (Int >> (lambda v: v if v ** 2 > 15 else 0)).check(5)
    5
    """

    def __or__(cls, other):
        return cls() | other

    def __rshift__(cls, other):
        return cls() >> other


@py3metafix
class Trafaret(object):

    """
    Base class for trafarets, provides only one method for
    trafaret validation failure reporting

    Check that converters can be stacked
    >>> (Int() >> (lambda x: x * 2) >> (lambda x: x * 3)).check(1)
    6

    Check order
    >>> (Int() >> float >> str).check(4)
    '4.0'
    """

    __metaclass__ = TrafaretMeta

    def check(self, value):
        """
        Implement this method in Trafaret subclasses
        """
        if hasattr(self, '_check'):
            self._check(value)
            return self._convert(value)
        if hasattr(self, '_check_val'):
            return self._convert(self._check_val(value))
        cls = "%s.%s" % (type(self).__module__, type(self).__name__)
        raise NotImplementedError("method check is not implemented in"
                                  " '%s'" % cls)

    def converter(self, value):
        """
        You can change converter with `>>` operator
        """
        return value

    def _convert(self, value):
        val = value
        for converter in getattr(self, 'converters', [self.converter]):
            val = converter(val)
        return val

    def _failure(self, error=None):
        """
        Shortcut method for raising validation error
        """
        raise DataError(error=error)

    def _trafaret(self, trafaret):
        """
        Helper for complex trafarets, takes trafaret instance or class
        and returns trafaret instance
        """
        if isinstance(trafaret, Trafaret) or inspect.isroutine(trafaret):
            return trafaret
        elif issubclass(trafaret, Trafaret):
            return trafaret()
        elif isinstance(trafaret, type):
            return Type(trafaret)
        else:
            raise RuntimeError("%r should be instance or subclass"
                               " of Trafaret" % trafaret)

    def append(self, converter):
        """
        Appends new converter to list.
        """
        if hasattr(self, 'converters'):
            self.converters.append(converter)
        else:
            self.converters = [converter]
        return self

    def __or__(self, other):
        return Or(self, other)

    def __rshift__(self, other):
        self.append(other)
        return self


class TypeMeta(TrafaretMeta):

    def __getitem__(self, type_):
        return self(type_)


@py3metafix
class Type(Trafaret):

    """
    >>> Type(int)
    <Type(int)>
    >>> Type[int]
    <Type(int)>
    >>> c = Type[int]
    >>> c.check(1)
    1
    >>> extract_error(c, "foo")
    'value is not int'
    """
    __metaclass__ = TypeMeta

    def __init__(self, type_):
        self.type_ = type_

    def _check(self, value):
        if not isinstance(value, self.type_):
            self._failure("value is not %s" % self.type_.__name__)

    def __repr__(self):
        return "<Type(%s)>" % self.type_.__name__


class Any(Trafaret):

    """
    >>> Any()
    <Any>
    >>> (Any() >> ignore).check(object())
    """

    def _check(self, value):
        pass

    def __repr__(self):
        return "<Any>"


class OrMeta(TrafaretMeta):

    """
    Allows to use "<<" operator on Or class

    >>> Or << Int << String
    <Or(<Int>, <String>)>
    """

    def __lshift__(cls, other):
        return cls() << other


@py3metafix
class Or(Trafaret):

    """
    >>> nullString = Or(String, Null)
    >>> nullString
    <Or(<String>, <Null>)>
    >>> nullString.check(None)
    >>> nullString.check("test")
    'test'
    >>> extract_error(nullString, 1)
    {0: 'value is not string', 1: 'value should be None'}
    """

    __metaclass__ = OrMeta

    def __init__(self, *trafarets):
        self.trafarets = list(map(self._trafaret, trafarets))

    def _check_val(self, value):
        errors = []
        for trafaret in self.trafarets:
            try:
                return trafaret.check(value)
            except DataError as e:
                errors.append(e)
        raise DataError(dict(enumerate(errors)))

    def __lshift__(self, trafaret):
        self.trafarets.append(self._trafaret(trafaret))
        return self

    def __or__(self, trafaret):
        self << trafaret
        return self

    def __repr__(self):
        return "<Or(%s)>" % (", ".join(map(repr, self.trafarets)))


class Null(Trafaret):

    """
    >>> Null()
    <Null>
    >>> Null().check(None)
    >>> extract_error(Null(), 1)
    'value should be None'
    """

    def _check(self, value):
        if value is not None:
            self._failure("value should be None")

    def __repr__(self):
        return "<Null>"


class Bool(Trafaret):

    """
    >>> Bool()
    <Bool>
    >>> Bool().check(True)
    True
    >>> Bool().check(False)
    False
    >>> extract_error(Bool(), 1)
    'value should be True or False'
    """

    def _check(self, value):
        if not isinstance(value, bool):
            self._failure("value should be True or False")

    def __repr__(self):
        return "<Bool>"


class NumberMeta(TrafaretMeta):

    """
    Allows slicing syntax for min and max arguments for
    number trafarets

    >>> Int[1:]
    <Int(gte=1)>
    >>> Int[1:10]
    <Int(gte=1, lte=10)>
    >>> Int[:10]
    <Int(lte=10)>
    >>> Float[1:]
    <Float(gte=1)>
    >>> Int > 3
    <Int(gt=3)>
    >>> 1 < (Float < 10)
    <Float(gt=1, lt=10)>
    >>> (Int > 5).check(10)
    10
    >>> extract_error(Int > 5, 1)
    'value should be greater than 5'
    >>> (Int < 3).check(1)
    1
    >>> extract_error(Int < 3, 3)
    'value should be less than 3'
    """

    def __getitem__(cls, slice_):
        return cls(gte=slice_.start, lte=slice_.stop)

    def __lt__(cls, lt):
        return cls(lt=lt)

    def __gt__(cls, gt):
        return cls(gt=gt)


@py3metafix
class Float(Trafaret):

    """
    >>> Float()
    <Float>
    >>> Float(gte=1)
    <Float(gte=1)>
    >>> Float(lte=10)
    <Float(lte=10)>
    >>> Float(gte=1, lte=10)
    <Float(gte=1, lte=10)>
    >>> Float().check(1.0)
    1.0
    >>> extract_error(Float(), 1 + 3j)
    'value is not float'
    >>> extract_error(Float(), 1)
    1.0
    >>> Float(gte=2).check(3.0)
    3.0
    >>> extract_error(Float(gte=2), 1.0)
    'value is less than 2'
    >>> Float(lte=10).check(5.0)
    5.0
    >>> extract_error(Float(lte=3), 5.0)
    'value is greater than 3'
    >>> Float().check("5.0")
    5.0
    """

    __metaclass__ = NumberMeta

    convertable = str_types + (numbers.Real,)
    value_type = float

    def __init__(self, gte=None, lte=None, gt=None, lt=None):
        self.gte = gte
        self.lte = lte
        self.gt = gt
        self.lt = lt

    def _converter(self, val):
        if not isinstance(val, self.convertable):
            self._failure('value is not %s' % self.value_type.__name__)
        try:
            return self.value_type(val)
        except ValueError:
            self._failure("value can't be converted to %s" %
                          self.value_type.__name__)

    def _check_val(self, val):
        if not isinstance(val, self.value_type):
            value = self._converter(val)
        else:
            value = val
        if self.gte is not None and value < self.gte:
            self._failure("value is less than %s" % self.gte)
        if self.lte is not None and value > self.lte:
            self._failure("value is greater than %s" % self.lte)
        if self.lt is not None and value >= self.lt:
            self._failure("value should be less than %s" % self.lt)
        if self.gt is not None and value <= self.gt:
            self._failure("value should be greater than %s" % self.gt)
        return value

    def __lt__(self, lt):
        return type(self)(gte=self.gte, lte=self.lte, gt=self.gt, lt=lt)

    def __gt__(self, gt):
        return type(self)(gte=self.gte, lte=self.lte, gt=gt, lt=self.lt)

    def __repr__(self):
        r = "<%s" % type(self).__name__
        options = []
        for param in ("gte", "lte", "gt", "lt"):
            if getattr(self, param) is not None:
                options.append("%s=%s" % (param, getattr(self, param)))
        if options:
            r += "(%s)" % (", ".join(options))
        r += ">"
        return r


class Int(Float):

    """
    >>> Int()
    <Int>
    >>> Int().check(5)
    5
    >>> extract_error(Int(), 1.1)
    'value is not int'
    >>> extract_error(Int(), 1 + 1j)
    'value is not int'
    """

    value_type = int

    def _converter(self, val):
        if isinstance(val, float):
            if not val.is_integer():
                self._failure('value is not int')
        return super(Int, self)._converter(val)


class Atom(Trafaret):

    """
    >>> Atom('atom').check('atom')
    'atom'
    >>> extract_error(Atom('atom'), 'molecule')
    "value is not exactly 'atom'"
    """

    def __init__(self, value):
        self.value = value

    def _check(self, value):
        if self.value != value:
            self._failure("value is not exactly '%s'" % self.value)


class String(Trafaret):

    """
    >>> String()
    <String>
    >>> String(allow_blank=True)
    <String(blank)>
    >>> String().check("foo")
    'foo'
    >>> extract_error(String(), "")
    'blank value is not allowed'
    >>> String(allow_blank=True).check("")
    ''
    >>> extract_error(String(), 1)
    'value is not string'
    >>> String(regex='\w+').check('wqerwqer')
    'wqerwqer'
    >>> extract_error(String(regex='^\w+$'), 'wqe rwqer')
    'value does not match pattern'
    """

    def __init__(self, allow_blank=False, regex=None):
        self.allow_blank = allow_blank
        self.regex = re.compile(regex) if isinstance(regex, str_types) else regex

    def _check_val(self, value):
        if not isinstance(value, str_types):
            self._failure("value is not string")
        if not self.allow_blank and len(value) is 0:
            self._failure("blank value is not allowed")
        if self.regex is not None:
            match = self.regex.match(value)
            if not match:
                self._failure("value does not match pattern")
            return match
        return value

    def converter(self, value):
        if isinstance(value, str_types):
            return value
        return value.group()

    def __repr__(self):
        return "<String(blank)>" if self.allow_blank else "<String>"


class Email(String):

    """
    >>> Email().check('someone@example.net')
    'someone@example.net'
    >>> (Email() >> (lambda m: m.groupdict()['domain'])).check('someone@example.net')
    'example.net'
    >>> extract_error(Email(),'foo')
    'foo value is not an email'
    """

    regex = re.compile(
        r"(?P<name>^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
        r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-011\013\014\016-\177])*"' # quoted-string
        r')@(?P<domain>(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?$)'  # domain
        r'|\[(25[0-5]|2[0-4]\d|[0-1]?\d?\d)(\.(25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}\]$', 
        re.IGNORECASE # literal form, ipv4 address (SMTP 4.1.3)
    )

    def __init__(self, allow_blank=False):
        self.allow_blank = allow_blank

    def _check_val(self, value):
        try:
            return super(Email, self)._check_val(value)
        except DataError:
            # Trivial case failed. Try for possible IDN domain-part
            if value and '@' in value:
                parts = value.split('@')
                try:
                    parts[-1] = parts[-1].encode('idna')
                except UnicodeError:
                    pass
                else:
                    return super(Email, self)._check_val('@'.join(parts))
        self._failure('%s value is not an email' % value)

    def __repr__(self):
        return '<Email>'


class URL(String):

    """
    >>> URL().check('http://example.net/resource/?param=value#anchor')
    'http://example.net/resource/?param=value#anchor'
    >>> str(URL().check('http://пример.рф/resource/?param=value#anchor'))
    'http://xn--e1afmkfd.xn--p1ai/resource/?param=value#anchor'
    """

    regex = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
        r'localhost|' #localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    def __init__(self, allow_blank=False):
        self.allow_blank = allow_blank

    def _check_val(self, value):
        try:
            return super(URL, self)._check_val(value)
        except DataError:
            # Trivial case failed. Try for possible IDN domain-part
            if value:
                if isinstance(value, bytes):
                    decoded = value.decode('utf-8')
                else:
                    decoded = value
                scheme, netloc, path, query, fragment = urlparse.urlsplit(decoded)
                try:
                    netloc = netloc.encode('idna').decode('ascii') # IDN -> ACE
                except UnicodeError: # invalid domain part
                    pass
                else:
                    url = urlparse.urlunsplit((scheme, netloc, path, query, fragment))
                    return super(URL, self)._check_val(url)
        self._failure('value is not URL')

    def __repr__(self):
        return '<URL>'


class SquareBracketsMeta(TrafaretMeta):

    """
    Allows usage of square brackets for List initialization

    >>> List[Int]
    <List(<Int>)>
    >>> List[Int, 1:]
    <List(min_length=1 | <Int>)>
    >>> List[:10, Int]
    <List(max_length=10 | <Int>)>
    >>> List[1:10]
    Traceback (most recent call last):
    ...
    RuntimeError: Trafaret is required for List initialization
    """

    def __getitem__(self, args):
        slice_ = None
        trafaret = None
        if not isinstance(args, tuple):
            args = (args, )
        for arg in args:
            if isinstance(arg, slice):
                slice_ = arg
            elif isinstance(arg, Trafaret) or issubclass(arg, Trafaret) \
                 or isinstance(arg, type):
                trafaret = arg
        if not trafaret:
            raise RuntimeError("Trafaret is required for List initialization")
        if slice_:
            return self(trafaret, min_length=slice_.start or 0,
                                  max_length=slice_.stop)
        return self(trafaret)


@py3metafix
class List(Trafaret):

    """
    >>> List(Int)
    <List(<Int>)>
    >>> List(Int, min_length=1)
    <List(min_length=1 | <Int>)>
    >>> List(Int, min_length=1, max_length=10)
    <List(min_length=1, max_length=10 | <Int>)>
    >>> extract_error(List(Int), 1)
    'value is not list'
    >>> List(Int).check([1, 2, 3])
    [1, 2, 3]
    >>> List(String).check(["foo", "bar", "spam"])
    ['foo', 'bar', 'spam']
    >>> extract_error(List(Int), [1, 2, 1 + 3j])
    {2: 'value is not int'}
    >>> List(Int, min_length=1).check([1, 2, 3])
    [1, 2, 3]
    >>> extract_error(List(Int, min_length=1), [])
    'list length is less than 1'
    >>> List(Int, max_length=2).check([1, 2])
    [1, 2]
    >>> extract_error(List(Int, max_length=2), [1, 2, 3])
    'list length is greater than 2'
    >>> extract_error(List(Int), ["a"])
    {0: "value can't be converted to int"}
    """

    __metaclass__ = SquareBracketsMeta

    def __init__(self, trafaret, min_length=0, max_length=None):
        self.trafaret = self._trafaret(trafaret)
        self.min_length = min_length
        self.max_length = max_length

    def _check_val(self, value):
        if not isinstance(value, list):
            self._failure("value is not list")
        if len(value) < self.min_length:
            self._failure("list length is less than %s" % self.min_length)
        if self.max_length is not None and len(value) > self.max_length:
            self._failure("list length is greater than %s" % self.max_length)
        lst = []
        errors = {}
        for index, item in enumerate(value):
            try:
                lst.append(self.trafaret.check(item))
            except DataError as err:
                errors[index] = err
        if errors:
            raise DataError(error=errors)
        return lst

    def __repr__(self):
        r = "<List("
        options = []
        if self.min_length:
            options.append("min_length=%s" % self.min_length)
        if self.max_length:
            options.append("max_length=%s" % self.max_length)
        r += ", ".join(options)
        if options:
            r += " | "
        r += repr(self.trafaret)
        r += ")>"
        return r


class Key(object):

    """
    Helper class for Dict.
    """

    def __init__(self, name, default=None, optional=False, to_name=None):
        self.name = name
        self.to_name = to_name
        self.default = default
        self.optional = optional
        self.trafaret = Any()

    def pop(self, data):
        if self.name in data or self.default is not None:
            yield self.get_name(), catch_error(self.trafaret,
                    data.pop(self.name, self.default))
            raise StopIteration
        if not self.optional:
            yield self.name, DataError(error='is required')

    def keys_names(self):
        yield self.name

    def set_trafaret(self, trafaret):
        self.trafaret = trafaret

    def __rshift__(self, name):
        self.to_name = name
        return self

    def get_name(self):
        return self.to_name or self.name

    def make_optional(self):
        self.optional = True
        self.default = None


class Dict(Trafaret):

    """
    >>> trafaret = Dict(foo=Int, bar=String) >> ignore
    >>> trafaret.check({"foo": 1, "bar": "spam"})
    >>> extract_error(trafaret, {"foo": 1, "bar": 2})
    {'bar': 'value is not string'}
    >>> extract_error(trafaret, {"foo": 1})
    {'bar': 'is required'}
    >>> extract_error(trafaret, {"foo": 1, "bar": "spam", "eggs": None})
    {'eggs': 'eggs is not allowed key'}
    >>> trafaret.allow_extra("eggs")
    <Dict(extras=(eggs) | bar=<String>, foo=<Int>)>
    >>> trafaret.check({"foo": 1, "bar": "spam", "eggs": None})
    >>> trafaret.check({"foo": 1, "bar": "spam"})
    >>> extract_error(trafaret, {"foo": 1, "bar": "spam", "ham": 100})
    {'ham': 'ham is not allowed key'}
    >>> trafaret.allow_extra("*")
    <Dict(any, extras=(eggs) | bar=<String>, foo=<Int>)>
    >>> trafaret.check({"foo": 1, "bar": "spam", "ham": 100})
    >>> trafaret.check({"foo": 1, "bar": "spam", "ham": 100, "baz": None})
    >>> extract_error(trafaret, {"foo": 1, "ham": 100, "baz": None})
    {'bar': 'is required'}
    >>> trafaret = Dict({Key('bar', optional=True): String}, foo=Int) >> ignore
    >>> trafaret.allow_extra("*")
    <Dict(any | bar=<String>, foo=<Int>)>
    >>> trafaret.check({"foo": 1, "ham": 100, "baz": None})
    >>> extract_error(trafaret, {"bar": 1, "ham": 100, "baz": None})
    {'foo': 'is required', 'bar': 'value is not string'}
    >>> extract_error(trafaret, {"foo": 1, "bar": 1, "ham": 100, "baz": None})
    {'bar': 'value is not string'}
    >>> trafaret = Dict({Key('bar', default='nyanya') >> 'baz': String}, foo=Int)
    >>> trafaret.check({'foo': 4})
    {'foo': 4, 'baz': 'nyanya'}
    >>> _ = trafaret.ignore_extra('fooz')
    >>> trafaret.check({'foo': 4, 'fooz': 5})
    {'foo': 4, 'baz': 'nyanya'}
    >>> _ = trafaret.ignore_extra('*')
    >>> trafaret.check({'foo': 4, 'foor': 5})
    {'foo': 4, 'baz': 'nyanya'}
    """

    def __init__(self, keys={}, **trafarets):
        self.extras = []
        self.allow_any = False
        self.ignore = []
        self.ignore_any = False
        self.keys = []
        for key, trafaret in itertools.chain(trafarets.items(), keys.items()):
            key_ = key if isinstance(key, Key) else Key(key)
            key_.set_trafaret(self._trafaret(trafaret))
            self.keys.append(key_)

    def allow_extra(self, *names):
        for name in names:
            if name == "*":
                self.allow_any = True
            else:
                self.extras.append(name)
        return self

    def ignore_extra(self, *names):
        for name in names:
            if name == "*":
                self.ignore_any = True
            else:
                self.ignore.append(name)
        return self

    def make_optional(self, *args):
        for key in self.keys:
            if key.name in args or '*' in args:
                key.make_optional()

    def _check_val(self, value):
        if not isinstance(value, dict):
            self._failure("value is not dict")
        data = copy.copy(value)
        collect = {}
        errors = {}
        for key in self.keys:
            for k, v in key.pop(data):
                if isinstance(v, DataError):
                    errors[k] = v
                else:
                    collect[k] = v
        if not self.ignore_any:
            for key in data:
                if key in self.ignore:
                    continue
                if not self.allow_any and key not in self.extras:
                    errors[key] = DataError("%s is not allowed key" % key)
                else:
                    collect[key] = data
        if errors:
            raise DataError(error=errors)
        return collect

    def keys_names(self):
        for key in self.keys:
            for k in key.keys_names():
                yield k

    def __repr__(self):
        r = "<Dict("
        options = []
        if self.allow_any:
            options.append("any")
        if self.ignore:
            options.append("ignore=(%s)" % (", ".join(self.ignore)))
        if self.extras:
            options.append("extras=(%s)" % (", ".join(self.extras)))
        r += ", ".join(options)
        if options:
            r += " | "
        options = []
        for key in sorted(self.keys, key=lambda k: k.name):
            options.append("%s=%r" % (key.name, key.trafaret))
        r += ", ".join(options)
        r += ")>"
        return r


class Mapping(Trafaret):

    """
    >>> trafaret = Mapping(String, Int)
    >>> trafaret
    <Mapping(<String> => <Int>)>
    >>> trafaret.check({"foo": 1, "bar": 2})
    {'foo': 1, 'bar': 2}
    >>> extract_error(trafaret, {"foo": 1, "bar": None})
    {'bar': {'value': 'value is not int'}}
    >>> extract_error(trafaret, {"foo": 1, 2: "bar"})
    {2: {'key': 'value is not string', 'value': "value can't be converted to int"}}
    """

    def __init__(self, key, value):
        self.key = self._trafaret(key)
        self.value = self._trafaret(value)

    def _check_val(self, mapping):
        checked_mapping = {}
        errors = {}
        for key, value in mapping.items():
            pair_errors = {}
            try:
                checked_key = self.key.check(key)
            except DataError as err:
                pair_errors['key'] = err
            try:
                checked_value = self.value.check(value)
            except DataError as err:
                pair_errors['value'] = err
            if pair_errors:
                errors[key] = DataError(error=pair_errors)
            else:
                checked_mapping[checked_key] = checked_value
        if errors:
            raise DataError(error=errors)
        return checked_mapping

    def __repr__(self):
        return "<Mapping(%r => %r)>" % (self.key, self.value)


class Enum(Trafaret):

    """
    >>> trafaret = Enum("foo", "bar", 1) >> ignore
    >>> trafaret
    <Enum('foo', 'bar', 1)>
    >>> trafaret.check("foo")
    >>> trafaret.check(1)
    >>> extract_error(trafaret, 2)
    "value doesn't match any variant"
    """

    def __init__(self, *variants):
        self.variants = variants[:]

    def _check(self, value):
        if value not in self.variants:
            self._failure("value doesn't match any variant")

    def __repr__(self):
        return "<Enum(%s)>" % (", ".join(map(repr, self.variants)))


class Callable(Trafaret):

    """
    >>> (Callable() >> ignore).check(lambda: 1)
    >>> extract_error(Callable(), 1)
    'value is not callable'
    """

    def _check(self, value):
        if not callable(value):
            self._failure("value is not callable")

    def __repr__(self):
        return "<CallableC>"


class Call(Trafaret):

    """
    >>> def validator(value):
    ...     if value != "foo":
    ...         return DataError("I want only foo!")
    ...     return 'foo'
    ...
    >>> trafaret = Call(validator)
    >>> trafaret
    <CallC(validator)>
    >>> trafaret.check("foo")
    'foo'
    >>> extract_error(trafaret, "bar")
    'I want only foo!'
    """

    def __init__(self, fn):
        if not callable(fn):
            raise RuntimeError("CallC argument should be callable")
        argspec = inspect.getargspec(fn)
        if len(argspec.args) - len(argspec.defaults or []) > 1:
            raise RuntimeError("CallC argument should be"
                               " one argument function")
        self.fn = fn

    def _check_val(self, value):
        res = self.fn(value)
        if isinstance(res, DataError):
            raise res
        else:
            return res

    def __repr__(self):
        return "<CallC(%s)>" % self.fn.__name__


class Forward(Trafaret):

    """
    >>> node = Forward()
    >>> node << Dict(name=String, children=List[node])
    >>> node
    <Forward(<Dict(children=<List(<recur>)>, name=<String>)>)>
    >>> node.check({"name": "foo", "children": []}) == {'children': [], 'name': 'foo'}
    True
    >>> extract_error(node, {"name": "foo", "children": [1]})
    {'children': {0: 'value is not dict'}}
    >>> node.check({"name": "foo", "children": [ \
                        {"name": "bar", "children": []} \
                     ]}) == {'children': [{'children': [], 'name': 'bar'}], 'name': 'foo'}
    True
    """

    def __init__(self):
        self.trafaret = None
        self._recur_repr = False

    def __lshift__(self, trafaret):
        self.provide(trafaret)

    def provide(self, trafaret):
        if self.trafaret:
            raise RuntimeError("trafaret for Forward is already specified")
        self.trafaret = self._trafaret(trafaret)

    def _check_val(self, value):
        return self.trafaret.check(value)

    def __repr__(self):
        # XXX not threadsafe
        if self._recur_repr:
            return "<recur>"
        self._recur_repr = True
        r = "<Forward(%r)>" % self.trafaret
        self._recur_repr = False
        return r


class GuardError(DataError):

    """
    Raised when guarded function gets invalid arguments,
    inherits error message from corresponding DataError
    """

    pass


def guard(trafaret=None, **kwargs):
    """
    Decorator for protecting function with trafarets

    >>> @guard(a=String, b=Int, c=String)
    ... def fn(a, b, c="default"):
    ...     '''docstring'''
    ...     return (a, b, c)
    ...
    >>> fn.__module__ = None
    >>> help(fn)
    Help on function fn:
    <BLANKLINE>
    fn(*args, **kwargs)
        guarded with <Dict(a=<String>, b=<Int>, c=<String>)>
    <BLANKLINE>
        docstring
    <BLANKLINE>
    >>> fn("foo", 1)
    ('foo', 1, 'default')
    >>> extract_error(fn, "foo", 1, 2)
    {'c': 'value is not string'}
    >>> extract_error(fn, "foo")
    {'b': 'is required'}
    >>> g = guard(Dict())
    >>> c = Forward()
    >>> c << Dict(name=str, children=List[c])
    >>> g = guard(c)
    >>> g = guard(Int())
    Traceback (most recent call last):
    ...
    RuntimeError: trafaret should be instance of Dict or Forward
    """
    if trafaret and not isinstance(trafaret, Dict) and \
                    not isinstance(trafaret, Forward):
        raise RuntimeError("trafaret should be instance of Dict or Forward")
    elif trafaret and kwargs:
        raise RuntimeError("choose one way of initialization,"
                           " trafaret or kwargs")
    if not trafaret:
        trafaret = Dict(**kwargs)

    def wrapper(fn):
        argspec = inspect.getargspec(fn)

        @functools.wraps(fn)
        def decor(*args, **kwargs):
            fnargs = argspec.args
            if fnargs[0] in ['self', 'cls']:
                fnargs = fnargs[1:]
                checkargs = args[1:]
            else:
                checkargs = args

            try:
                call_args = dict(
                    itertools.chain(zip(fnargs, checkargs), kwargs.items())
                )
                for name, default in zip(reversed(fnargs),
                                         argspec.defaults or ()):
                    if name not in call_args:
                        call_args[name] = default
                converted = trafaret.check(call_args)
            except DataError as err:
                raise GuardError(error=err.error)
            return fn(**converted)
        decor.__doc__ = "guarded with %r\n\n" % trafaret + (decor.__doc__ or "")
        return decor
    return wrapper


def ignore(val):

    """
    Stub to ignore value from trafaret
    Use it like:

    >>> a = Int >> ignore
    >>> a.check(7)
    """

    pass


def catch_error(checker, *a, **kw):

    """
    Helper for tests - catch error and return it as dict
    """

    try:
        if hasattr(checker, 'check'):
            return checker.check(*a, **kw)
        elif callable(checker):
            return checker(*a, **kw)
    except DataError as error:
        return error


def extract_error(checker, *a, **kw):

    """
    Helper for tests - catch error and return it as dict
    """

    res = catch_error(checker, *a, **kw)
    if isinstance(res, DataError):
        return res.as_dict()
    return res
