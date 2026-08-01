"""ai_shell.server — what llama-server is actually told to do.

The command line is the whole contract with the inference engine, and it is
the one part of starting a server that can be checked without starting one.
"""

import unittest

from ai_shell import config, server


class Argv(unittest.TestCase):
    def test_the_model_is_a_path_not_a_repo_reference(self):
        argv = server._argv("/bin/llama-server", "/models/model-q6_k.gguf")
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "/models/model-q6_k.gguf")
        # -hf would make llama.cpp fetch the weights itself, which is the
        # download this app took over precisely because it can't be resumed.
        self.assertNotIn("-hf", argv)

    def test_the_rest_of_the_flags_are_unchanged(self):
        argv = server._argv("/bin/llama-server", "/models/model.gguf")
        self.assertEqual(argv[0], "/bin/llama-server")
        self.assertEqual(argv[argv.index("--host") + 1], config.HOST)
        self.assertEqual(argv[argv.index("--port") + 1], str(config.PORT))
        self.assertEqual(argv[argv.index("-c") + 1], str(config.CONTEXT_SIZE))
        self.assertEqual(argv[argv.index("-ngl") + 1], str(config.GPU_LAYERS))
        self.assertIn("--jinja", argv)


if __name__ == "__main__":
    unittest.main()
