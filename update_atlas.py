"""Compatibility message; standalone Atlas updates are not supported in AA."""
class UpdateError(RuntimeError):
    pass


def main():
    print('Update AA using a verified release ZIP. See docs/updating-atlas.md.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
