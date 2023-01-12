import free_uploader


def main() -> int:
    return free_uploader.main("http://foo.free.fr/index.php", "ftpperso.free.fr", "foo", "bar")
