# Contributing

Contributions are welcome: bug reports, focused fixes, tests, and pull requests help improve the project.

## Before opening an issue

- Check whether the problem reproduces on the latest release or `main`.
- Include the application version, operating system, Python version (when running from source), command, and complete error message.
- Provide a minimal reproducible example where possible.
- Do not upload firmware images containing personal data, private keys, tokens, or content you are not allowed to redistribute.

## Before opening a pull request

1. Create a separate branch for the change.
2. Add tests for the new behavior and failure cases.
3. Run the complete test suite:

   ```bash
   python -m unittest discover -s tests -v
   ```

4. Update both README files when user-visible behavior or CLI options change.
5. Update the English and Russian documentation and changelog.
6. Avoid new third-party dependencies unless they are justified. The CLI should remain standard-library-only.
7. Keep the GUI as a client of `sparse_to_raw.py`; do not introduce a second Sparse parser or checksum implementation.

## Project principles

- Malformed input must produce an actionable error and a non-zero CLI exit code.
- A failed conversion or cancellation must not corrupt an existing destination.
- Process image data in bounded chunks rather than loading an entire image into memory.
- The application operates on files only; do not add phone flashing or partition-writing behavior.
