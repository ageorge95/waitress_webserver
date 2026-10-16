from sys import version_info

# Waitress supports Python 3.7+. This tool itself only relies on the
# standard library plus waitress, so no other version-specific
# incompatibilities are expected.
MIN_PYTHON = (3, 7)

current_python_version = (version_info.major, version_info.minor)

if current_python_version < MIN_PYTHON:
    raise Exception(
        f'Invalid python version {current_python_version[0]}.{current_python_version[1]} '
        f'(requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer)'
    )
else:
    print('Your python version seems fine. Proceeding ...')