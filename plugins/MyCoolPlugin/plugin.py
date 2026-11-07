from PyQt5.QtWidgets import QMessageBox

class Plugin:
    def __init__(self, ctx):
        self.ctx = ctx
        self.plugin_name = "Test"
        self.ctx.register_plugin_command(self.plugin_name, "Say Hello", self.say_hello)

    def say_hello(self):
        QMessageBox.information(self.ctx, "Hello", "Hello from plugin!")