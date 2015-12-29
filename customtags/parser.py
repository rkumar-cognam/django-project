from customtags.arguments import *


"""
This module is responsible for ensuring that all arguments are properly configured
and structured as a result of initialization
"""


def structure_arguments(arguments, tagname, nextargs_outside=None, is_optional=False):
    """
    This function scans backwards through the arguments, validating each one, and then
    attaching whatever configuration may be required for each according to type.  
    Also, for MultiArguments, it calls itself recursively, to allow all nested arguments
    to be visited.
    """
    # fixes the python bug where the default [] is treated as a mutable global
    nextargs_outside = nextargs_outside if nextargs_outside is not None else []

    len_arguments = len(arguments)
    if len_arguments == 0:
        return arguments

    # this is to allow scanning beyond the current list
    extended_args = list(arguments) + list(nextargs_outside)

    last_arg = arguments[len_arguments-1]
    if isinstance(last_arg, basestring):
        last_arg = arguments[len_arguments-1] = \
                   extended_args[len_arguments-1] = Constant(last_arg)

    last_arg.initialize(tagname)

    if isinstance(last_arg, MultiArgument):
        last_arg.arguments = structure_arguments(
            last_arg.arguments, last_arg.tagname, nextargs_outside,
            isinstance(last_arg, Optional)
        )

    structure_exclude_constant(exclusive_arg=last_arg, 
                               possible_constants=nextargs_outside)
    structure_possible_nodelist(possible_nodelist=last_arg, 
                                possible_block_tags=nextargs_outside)

    i = len_arguments-2
    j = len_arguments-1
    while i >= 0:

        current_arg = arguments[i] 
        visited_arg = arguments[j]
        already_visited_list = extended_args[j:]

        if isinstance(current_arg, EndTag):
            raise ImproperlyConfigured("EndTag should be the last argument.")

        if isinstance(current_arg, basestring):
            current_arg = arguments[i] = extended_args[i] = Constant(current_arg)

        current_arg.initialize(tagname)

        if isinstance(current_arg, MultiArgument):
            current_arg.arguments = structure_arguments(
                current_arg.arguments, current_arg.tagname, already_visited_list,
                isinstance(current_arg, Optional)
            )

        # set up for parsing
        structure_exclude_constant(exclusive_arg=current_arg, 
                                   possible_constants=already_visited_list)
        structure_possible_nodelist(possible_nodelist=current_arg, 
                                    possible_block_tags=already_visited_list)

        if not is_optional:
            current_arg, visited_arg = not_required_to_optional(current_arg, visited_arg)
            arguments[i] = extended_args[i] = current_arg

            # visited_arg is None when current_arg and visited_arg are merged into
            # a single Optional argument.  Here it is deleted from the trailing lists.

            if visited_arg is None:
                del arguments[j]
                del extended_args[j]
            else:
                arguments[j] = extended_args[j] = visited_arg 

        i -= 1
        j -= 1

    # If the first argument is not required, then this will wrap it in "optional".
    if not is_optional:
        throw_away, arguments[0] = not_required_to_optional(None, arguments[0])

    return arguments


def structure_exclude_constant(exclusive_arg, possible_constants):
    exclude = []
    for possible_constant in next_contained_first(possible_constants):
        if isinstance(possible_constant, Constant):
            exclude.append(possible_constant.value)

    if hasattr(exclusive_arg, 'exclude'):
        exclusive_arg.exclude += exclude


def structure_possible_nodelist(possible_nodelist, possible_block_tags):
    if isinstance(possible_nodelist, NodeList):
        endtags = possible_nodelist_endtags(possible_nodelist, possible_block_tags)
        possible_nodelist.endtags = tuple(endtags) 
    


def possible_nodelist_endtags(possible_nodelist, possible_block_tags):
    if possible_nodelist.explicit_endtags is not None:
        return possible_nodelist.explicit_endtags
    
    endtags = []
    for possible_block_tag in next_contained_first(possible_block_tags):
        if isinstance(possible_block_tag, OneOf):
            for argument in possible_block_tag.arguments:
                for arg in next_contained_argument([argument], firsts_only=True):
                    if not isinstance(arg, (BlockTag, EndTag)):
                        raise ImproperlyConfigured(
                            "NodeList requires that all OneOf arguments that "
                            "immediately follow it be of type BlockTag or EndTag."
                        )
                    endtags.append(arg.tagname)
            
        elif not isinstance(possible_block_tag, (BlockTag, EndTag)):
            raise ImproperlyConfigured(
                "NodeList requires that any optional or required arguments that "
                "immediately follow it be of type BlockTag or EndTag."
            )
        else:
            endtags.append(possible_block_tag.tagname)
    if not endtags:
        raise ImproperlyConfigured("NodeList cannot be the last argument.")

    return endtags 


def not_required_to_optional(first, second):
    if hasattr(second, 'required') and \
       not second.required:

        if isinstance(first, Constant):
            optional = Optional(first, second)
            optional.initialize(first.tagname)
            return optional, None

        elif not isinstance(second, Optional):
            optional = Optional(second)
            optional.initialize(second.tagname)
            return first, optional

    return first, second

