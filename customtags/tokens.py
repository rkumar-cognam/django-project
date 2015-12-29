# -*- coding: utf-8 -*-

import re

from customtags._compat import intern, iteritems
#from customtags._compat import next, iteritems, implements_iterator, text_type

TOKEN_ADD = intern('add')
TOKEN_ASSIGN = intern('assign')
TOKEN_COLON = intern('colon')
TOKEN_COMMA = intern('comma')
TOKEN_DIV = intern('div')
TOKEN_DOT = intern('dot')
TOKEN_EQ = intern('eq')
TOKEN_FLOORDIV = intern('floordiv')
TOKEN_GT = intern('gt')
TOKEN_GTEQ = intern('gteq')
TOKEN_LBRACE = intern('lbrace')
TOKEN_LBRACKET = intern('lbracket')
TOKEN_LPAREN = intern('lparen')
TOKEN_LT = intern('lt')
TOKEN_LTEQ = intern('lteq')
TOKEN_MOD = intern('mod')
TOKEN_MUL = intern('mul')
TOKEN_NE = intern('ne')
TOKEN_PIPE = intern('pipe')
TOKEN_POW = intern('pow')
TOKEN_RBRACE = intern('rbrace')
TOKEN_RBRACKET = intern('rbracket')
TOKEN_RPAREN = intern('rparen')
TOKEN_SEMICOLON = intern('semicolon')
TOKEN_SUB = intern('sub')
TOKEN_TILDE = intern('tilde')
TOKEN_WHITESPACE = intern('whitespace')
TOKEN_FLOAT = intern('float')
TOKEN_INTEGER = intern('integer')
TOKEN_NAME = intern('name')
TOKEN_STRING = intern('string')
TOKEN_OPERATOR = intern('operator')
TOKEN_BLOCK_BEGIN = intern('block_begin')
TOKEN_BLOCK_END = intern('block_end')
TOKEN_VARIABLE_BEGIN = intern('variable_begin')
TOKEN_VARIABLE_END = intern('variable_end')
TOKEN_RAW_BEGIN = intern('raw_begin')
TOKEN_RAW_END = intern('raw_end')
TOKEN_COMMENT_BEGIN = intern('comment_begin')
TOKEN_COMMENT_END = intern('comment_end')
TOKEN_COMMENT = intern('comment')
TOKEN_LINESTATEMENT_BEGIN = intern('linestatement_begin')
TOKEN_LINESTATEMENT_END = intern('linestatement_end')
TOKEN_LINECOMMENT_BEGIN = intern('linecomment_begin')
TOKEN_LINECOMMENT_END = intern('linecomment_end')
TOKEN_LINECOMMENT = intern('linecomment')
TOKEN_DATA = intern('data')
TOKEN_INITIAL = intern('initial')
TOKEN_EOF = intern('eof')

# bind operators to token types
OPERATORS = {
    '+':            TOKEN_ADD,
    '-':            TOKEN_SUB,
    '/':            TOKEN_DIV,
    '//':           TOKEN_FLOORDIV,
    '*':            TOKEN_MUL,
    '%':            TOKEN_MOD,
    '**':           TOKEN_POW,
    '~':            TOKEN_TILDE,
    '[':            TOKEN_LBRACKET,
    ']':            TOKEN_RBRACKET,
    '(':            TOKEN_LPAREN,
    ')':            TOKEN_RPAREN,
    '{':            TOKEN_LBRACE,
    '}':            TOKEN_RBRACE,
    '==':           TOKEN_EQ,
    '!=':           TOKEN_NE,
    '>':            TOKEN_GT,
    '>=':           TOKEN_GTEQ,
    '<':            TOKEN_LT,
    '<=':           TOKEN_LTEQ,
    '=':            TOKEN_ASSIGN,
    '.':            TOKEN_DOT,
    ':':            TOKEN_COLON,
    '|':            TOKEN_PIPE,
    ',':            TOKEN_COMMA,
    ';':            TOKEN_SEMICOLON
}


# static regular expressions
whitespace_re = re.compile(r'\s+', re.U)
string_re = re.compile(r"('([^'\\]*(?:\\.[^'\\]*)*)'"
                       r'|"([^"\\]*(?:\\.[^"\\]*)*)")', re.S)
integer_re = re.compile(r'\d+')

# we use the unicode identifier rule if this python version is able
# to handle unicode identifiers, otherwise the standard ASCII one.
try:
    compile('föö', '<unknown>', 'eval')
except SyntaxError:
    name_re = re.compile(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b')
else:
    from blended_tags import _stringdefs
    name_re = re.compile(r'[%s][%s]*' % (_stringdefs.xid_start,
                                         _stringdefs.xid_continue))

float_re = re.compile(r'(?<!\.)\d+\.\d+')
newline_re = re.compile(r'(\r\n|\r|\n)')

# bind operators to token types
operators = OPERATORS

reverse_operators = dict([(v, k) for k, v in iteritems(operators)])
assert len(operators) == len(reverse_operators), 'operators dropped'

operator_re = re.compile('(%s)' % '|'.join(re.escape(x) for x in
                         sorted(operators, key=lambda x: -len(x))))


ignored_tokens = frozenset([TOKEN_COMMENT_BEGIN, TOKEN_COMMENT,
                            TOKEN_COMMENT_END, TOKEN_WHITESPACE,
                            TOKEN_WHITESPACE, TOKEN_LINECOMMENT_BEGIN,
                            TOKEN_LINECOMMENT_END, TOKEN_LINECOMMENT])
ignore_if_empty = frozenset([TOKEN_WHITESPACE, TOKEN_DATA,
                             TOKEN_COMMENT, TOKEN_LINECOMMENT])


def _describe_token_type(token_type):
    if token_type in reverse_operators:
        return reverse_operators[token_type]
    return {
        TOKEN_COMMENT_BEGIN:        'begin of comment',
        TOKEN_COMMENT_END:          'end of comment',
        TOKEN_COMMENT:              'comment',
        TOKEN_LINECOMMENT:          'comment',
        TOKEN_BLOCK_BEGIN:          'begin of statement block',
        TOKEN_BLOCK_END:            'end of statement block',
        TOKEN_VARIABLE_BEGIN:       'begin of print statement',
        TOKEN_VARIABLE_END:         'end of print statement',
        TOKEN_LINESTATEMENT_BEGIN:  'begin of line statement',
        TOKEN_LINESTATEMENT_END:    'end of line statement',
        TOKEN_DATA:                 'template data / text',
        TOKEN_EOF:                  'end of template'
    }.get(token_type, token_type)


def describe_token(token):
    """Returns a description of the token."""
    if token.type == 'name':
        return token.value
    return _describe_token_type(token.type)


def describe_token_expr(expr):
    """Like `describe_token` but for token expressions."""
    if ':' in expr:
        type, value = expr.split(':', 1)
        if type == 'name':
            return value
    else:
        type = expr
    return _describe_token_type(type)


