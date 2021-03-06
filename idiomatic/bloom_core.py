#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Fluent code generator

XXX THIS CODE IS CURRENTLY UNSTABLE.

This module takes in Bloom-like DSL files and generates 
fluent-compatible C++ implementations as header files to
be included in a C++ driver program.

The Bloom DSL file has the format:
    <... FIX ME ...>


Example:
  In this example, the target we build is a `.dylib`
  file suitable for linking into Python. It contains code
  for both a server and a client.
    $ python fluentgen.py client.yml -o client.h
    $ python fluentgen.py server.yml -o server.h
    $ g++  -std=c++14 -Wall -c -g -I../fluent/src -I../fluent/build/Debug/vendor/googletest/src/googletest/googletest/include -I../fluent/build/Debug/vendor/range-v3/range-v3-prefix/src/range-v3/include -Wall -Wextra -Werror -pedantic  -c fluentchat.cc
    $ g++  -Wall -g -dynamiclib fluentchat.o -L../fluent/build/Debug/fluent -lfluent -lzmq -lglog -lfmt -o fluentchat.dylib

  the context of fluentchat.cc is

Attributes:
  This module has no module-level variables

Todo:
  * test on more examples
  * think about modularity (e.g. the `import` feature of Bud)

"""
from collections import defaultdict,OrderedDict
import pprint
from bloom import BloomParser

class BloomSemantics(object):
  """Tatsu semantics file for handling different tokens in the grammar
  """
  boot_state = False
  schema = {}
  boot_rules = {}
  rules = {}
  tups = {}
  tupbuf = []
  varnum = 0

  def start(self, ast):
    """start of the parser semantics

    Args:
      ast (str): Tatsu AST

    Returns:
      str: parsed output, namely C++ code
    """
    # prologue
    retval = self.fluent_prologue(ast.name, ast.args)

    # schema
    retval += '''
    ///////////////
    // Bloom Schema
'''
    retval += '\n'.join(('    .' + l) for l in self.translate_schema(self.schema))
    retval += '''
    ///////////////
    ;
'''

    # constant tuples
    for k in self.tups.keys():
      # first the type
      retval += '  using ' + k + '_tuple_t = std::tuple<'
      retval += ', '.join(v for _,v in self.schema[k]['cols'].items())
      retval += '>;\n'
      # then the constant collection
      retval += '  std::vector<' + k + '_tuple_t> ' + k + '_tuples = {\n'
      retval += (';\n'.join('    std::make_tuple(' + ', '.join(a.strip() for a in tup) + ')' for tup in self.tups[k]))
      retval += '\n  };\n'

    # bootstrap logic
    retval += self.register_rules(True, ast.boot_logic)
    # bloom logic
    retval += self.register_rules(False, ast.logic)

    # epilogue
    retval += self.fluent_epilogue(ast.name)
    return retval

  def attrs(self, ast):
    return ast

  def set_boot(self, ast):
    self.boot_state = True
    return ast

  def unset_boot(self, ast):
    self.boot_state = False
    return ast

  def register_rules(self, bootp, rules):
    """generate the C++ to wrap the rule definitions

    Args:
      bootp (bool): whether these are bootstrap rules

      rules (str): C++ translation of rules

    Returns:
      str: C++ code wrapping all the rules passed in
    """

    if rules == None or len(rules) == 0:
      return ''

    bootstr = ("Bootstrap" if bootp else "")

    retval = "  auto bloom" + str(self.varnum) + " = std::move(bloom" 
    retval += str(self.varnum - 1) + ")\n"
    self.varnum += 1
    retval += "    .Register" + bootstr + "Rules([&]("
    retval += ", ".join(('auto& ' + k) for k in self.schema.keys())
    retval += ") {\n"
    retval += "\n".join('      (void)' + l + ';' for l in self.schema.keys())
    retval += '''
      using namespace fluent::infix;

      //////////////
      // Bloom ''' + bootstr + ''' Rules
'''
    retval += rules
    retval += '      return std::make_tuple('
    if (bootp):
      retval += ", ".join(self.boot_rules.keys()) + ');\n' 
    else:
      retval += ", ".join(self.rules.keys()) + ');\n' 
    retval += '''      //////////////
    })'''
    retval += (";\n" if bootp else "\n")
    return retval

  def logic(self, ast):
    """convert the logic ast to a single string

    Args:
      ast (AST): Tatsu AST

    Returns:
      str: the logic ast as a string
    """
    return ''.join(ast)

  def stmt(self, ast):
    """wrap a statement as a string

    Args:
      ast (AST): the ast for the statement

    Returns:
      str: semicolon-terminated C++ statement
    """
    if ast != '':
      return '      ' + ast + ';\n'
    else:
      return ast

  def ruledef(self, ast):
    """wrap a rule definition in C++ boilerplate

    Args:
      ast (AST): the ast for the statement

    Returns:
      str: properly-typed C++ assignment
    """
    if (self.boot_state):
      self.boot_rules[ast.var] = ast.rule
    else:
      self.rules[ast.var] = ast.rule
    return "auto " + ast.var + " = " + ast.rule     

  def rule(self, ast):
    """wrap a rule in C++ boilerplate,
       if the ast has no rhs, this is a rule injecting constant
       tuples (e.g. in a Bootstrap).

    Args:
      ast (AST): the ast for the statement

    Returns:
      str: properly-wrapped C++ assignment
    """
    if ast.rhs == None:
      self.tups[ast.lhs] = self.tupbuf
      self.tupbuf = []
      rhs = 'lra::make_iterable(&' + ast.lhs + '_tuples)'
    else:
      rhs = ast.rhs
    return ast.lhs + ' ' + ast.mtype + ' ' + rhs

  def catalog_entry(self, ast):
    """handle a simple table/channel reference
    as a special case, translate stdin to fluin, stdout to fluout

    Args:
      ast (AST): the ast for the statement

    Returns:
      str: the catalog entry as a string
    """
    retval = (''.join(ast))
    if (retval == 'stdin'):
      return 'fluin'
    elif (retval == 'stdout'):
      return 'fluout'
    else:
      return retval

  def rhs(self, ast):
    """wrap the rhs of a rule

    Args:
      ast (AST): the ast for the statement

    Returns:
      str: pipe-delimited fluent text
    """
    retval = "("
    if ast.anchor != None:
      retval += ast.anchor
      if ast.chain != None:
        retval += ' | '
    if ast.chain != None:
      retval += ' | '.join(ast.chain)
    if ast.tups != None:
      self.tupbuf = ast.tups
      return None

    return retval + ")"
    
  def op(self, ast):
    """wrap a fluent operator

    Args:
      ast (AST): the ast for the operator

    Returns:
      str: appropriately-wrapped C++
    """
    retval = ast.opname
    if ast.plist != None:
      retval += "<" + ','.join(ast.plist) + ">"
    retval += "("
    if type(ast.op_args) == list:
      retval += ', '.join(ast.op_args)
    elif ast.op_args != None:
      retval += '[&]'
      retval += '(const '
      retval += 'auto'
      retval += '& ' + ast.op_args.argname + ')'
      retval += ast.op_args.code.code
    retval += ')'
    return(retval)

  def opname(self, ast):
    """wrap an opname

    Args:
      ast (AST): the ast for the statement

    Returns:
      str: properly wrapped opname
    """
    return "lra::" + ast

  def rhs_catalog_entry(self, ast):
    return self.cwrap + "(&" + ast + ")"

  def where(self, ast):
    return "filter"

  def cross(self, ast):
    return "make_cross"

  def now(self, ast):
    return "<="

  def next(self, ast):
    return "+="

  def async(self, ast):
    return "<="

  def delete(self, ast):
    return "-="  

  def schemadef(self, ast):
    """wrap a schema definition.
    As a special case, translate stdin/stdout to fluin/fluout

    Args:
      ast (AST): the ast for the statement

    Returns:
      nothing, but side effect: sets self.schema
    """
    if ast.name == 'stdin':
      self.schema['fluin'] = None;
    elif ast.name == 'stdout':
      self.schema['fluout'] = None;
    else:
      collection_type = ast.type
      collection_name = ast.name
      cols = { i.attrname: i.type for i in ast.cols}
      self.schema[collection_name] = {
        'type': collection_type,
        'cols': cols
      }
    return ""

  def fluent_prologue(self, name, arguments):
    """Generate C++ file preamble.

    Args:
      name (str): project name from the Bloom DSL name key
      args (list): the Bloom DSL args key, used to pass in runtime configuration arguments

    Returns:
      str: C++ code for the top of the generated file
    """
    retval = '''#ifndef ''' + str.upper(name) + '''_H_
  #define ''' + str.upper(name) + '''_H_

  #include <vector>

  #include "zmq.hpp"

  #include "common/status.h"
  #include "common/mock_pickler.h"
  #include "fluent/fluent_builder.h"
  #include "fluent/fluent_executor.h"
  #include "fluent/infix.h"
  #include "lineagedb/connection_config.h"
  #include "lineagedb/noop_client.h"
  #include "lineagedb/to_sql.h"
  #include "ra/logical/all.h"
  #include "common/hash_util.h"

  namespace lra = fluent::ra::logical;

  struct ''' + name + '''Args {
  '''
    for i in arguments:
      retval += " " + i.type + " " + i.attrname + ";\n"
    retval += '''};

  int ''' + name + '''Main(const ''' + name + '''Args& args) {
    zmq::context_t context(1);
    fluent::lineagedb::ConnectionConfig connection_config;
    auto bloom''' + str(self.varnum)
    self.varnum += 1
    retval += '''= fluent::fluent<fluent::lineagedb::NoopClient,fluent::Hash,
                             fluent::lineagedb::ToSql,fluent::MockPickler,
                             std::chrono::system_clock>
                             ("'''
    retval += name + '''_" + std::to_string(rand()),
                                      args.address, &context,
                                      connection_config)
      .ConsumeValueOrDie();
    auto bloom''' + str(self.varnum);
    retval += ''' = std::move(bloom''' + str(self.varnum - 1)
    self.varnum += 1
    retval += ")\n"
    return retval

  def fluent_epilogue(self, name):
    """Generate C++ file postamble.

    Args:
      name (str): project name from the Bloom DSL name key

    Returns:
      str: C++ code for the bottom of the generated file
    """

    retval = '''
    .ConsumeValueOrDie();
      fluent::Status status = std::move(bloom'''
    retval += str(self.varnum - 1) + ''').Run();
      CHECK_EQ(fluent::Status::OK, status);

      return 0;
  }

  #endif  // ''' + str.upper(name) + '''_H_
  '''
    return retval

  def translate_schema(self, sdict):
    """convert Bloom DSL schema to a list of Fluent C++ collection definitions

    Args:
      sdict (dict): Bloom DSL entries for collection definitions

    Returns:
      list of str: list with entries with one of the following forms:
        "stdin()"
        "stdout()"
        "template collection_type <type1,...>(collection_name, {{name1, ...}})"
    """
    result = []
    for name, defn in sdict.items():
      # we ignore the definition for stdin and stdout
      if (name == 'fluin'):
        result.append('stdin' + '()')
      elif name == 'fluout':
        result.append('stdout' + '()')
      else:
        collection_type = defn['type']
        collection_name = name
        cols = defn['cols']
        colnames = ('"' + col + '"' for col in cols.keys())
        coltypes = cols.values()
        str = "template " + collection_type + "<"
        str += ", ".join(coltypes) + ">("
        str += '"' + collection_name + '", {{' + ', '.join(colnames) + '}})'
        result.append(str)
    return result


def fullparse(specFile):
  """convert Bloom spec to a Fluent C++ header file

  Args:
    specFile (str): path to the .yml file

  Returns:
    text of the C++ file
  """
  spec = open(specFile).read()
  sem = BloomSemantics();
  setattr(sem, "cwrap", "lra::make_collection")
  parser = BloomParser()
  retval = parser.parse(spec, semantics=sem)

  return retval
