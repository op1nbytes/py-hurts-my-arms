def command(name: str):
    def decorator(fn):
        fn._command_name = name
        return fn
    return decorator
