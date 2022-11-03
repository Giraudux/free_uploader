from argparse import ArgumentParser, FileType, Namespace
from base64 import b64encode
from enum import Enum
from hashlib import sha1
from http import HTTPStatus
from io import SEEK_END
import logging
from math import ceil
from os import EX_OK
from unittest.mock import DEFAULT
from urllib.request import urlopen
from urllib.parse import urlencode
from pathlib import Path
from datetime import datetime
from ftplib import FTP, error_perm
from importlib.resources import files, as_file
from zipfile import ZipFile
from urllib.parse import urlparse
from jinja2 import Environment, PackageLoader
from io import BytesIO

DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024
DEFAULT_MAX_TRY = 5
DEFAULT_FILES_PATH = "files"
DEFAULT_ELFINDER_PATH = "."
DEFAULT_HTML_TITLE = "Files"
DEFAULT_HTML_FAVICON = "&#128193;"


class ServerMode(Enum):
    DEFAULT = "default"
    UPLOAD = "upload"


logger = logging.getLogger(__name__)
server_modes_php_versions = {ServerMode.DEFAULT: "56", ServerMode.UPLOAD: ""}


def http_upload_chunk(url: str, data_post: str, max_try: int, try_count: int = 0) -> None:
    logger.debug(f"upload_chunk(url={url}, data_post=..., max_try={max_try}, try_count={try_count})")
    try:
        with urlopen(url, data_post) as response:
            if response.status != HTTPStatus.OK:
                raise Exception(response.read())
    except Exception as exception:
        logger.warning(exception)
        if try_count >= max_try:
            raise exception
        http_upload_chunk(url, data_post, max_try, try_count + 1)


def http_upload(args: Namespace) -> None:
    logger.debug("upload_file(args)")
    # arguments
    ftp_host = str(args.ftp_host)
    ftp_user = str(args.ftp_user)
    ftp_passwd = str(args.ftp_passwd)
    remote_file_path = Path(args.file_to_upload.name if args.remote_file_path is None else args.remote_file_path)
    http_url = str(args.http_url)
    file_to_upload: FileType = args.file_to_upload
    chunk_size = int(args.chunk_size)
    max_try = int(args.max_try)
    # body
    with FTP(ftp_host, ftp_user, ftp_passwd) as ftp:
        set_server_mode(ServerMode.UPLOAD, ftp)
    try:
        with file_to_upload as upload_file:
            upload_file.seek(0, SEEK_END)
            file_size = upload_file.tell()
            upload_file.seek(0)
            start_time = datetime.utcnow()
            while True:
                offset = upload_file.tell()
                data_bin = upload_file.read(chunk_size)
                if not data_bin:
                    break
                data_size = len(data_bin)
                data_sha1 = sha1(data_bin).hexdigest()
                data_b64 = b64encode(data_bin)
                remote_file_path_b64 = b64encode(str(remote_file_path).encode())
                data_post = urlencode(
                    {
                        "function": "upload",
                        "filepath_b64": remote_file_path_b64,
                        "checksum_sha1": data_sha1,
                        "size": data_size,
                        "offset": offset,
                        "data_b64": data_b64,
                    }
                ).encode("ascii")
                elapsed_time = datetime.utcnow() - start_time
                logger.info(
                    'uploading from "{}" to "{}", bytes: {}/{}, chunks: {}/{}, remaining time: {}'.format(
                        file_to_upload.name,
                        remote_file_path,
                        str(offset + data_size).rjust(len(str(file_size))),
                        file_size,
                        str(ceil((offset + data_size) / chunk_size)).rjust(len(str(ceil(file_size / chunk_size)))),
                        ceil(file_size / chunk_size),
                        ((elapsed_time * file_size) / offset) - elapsed_time if offset else 0,
                    )
                )
                http_upload_chunk(http_url, data_post, max_try)
                if data_size < chunk_size:
                    break
    finally:
        with FTP(ftp_host, ftp_user, ftp_passwd) as ftp:
            set_server_mode(ServerMode.DEFAULT, ftp)


def ftp_remove(args: Namespace) -> None:
    logger.debug("ftp_remove(args)")
    # arguments
    ftp_host = str(args.ftp_host)
    ftp_user = str(args.ftp_user)
    ftp_passwd = str(args.ftp_passwd)
    dir = bool(args.dir)
    remote_path = Path(args.remote_path)
    # body
    with FTP(ftp_host, ftp_user, ftp_passwd) as ftp:
        if dir:
            ftp.rmd(str(remote_path))
        else:
            ftp.delete(str(remote_path))


def ftp_list(args: Namespace) -> None:
    logger.debug("ftp_list(args)")
    # arguments
    ftp_host = str(args.ftp_host)
    ftp_user = str(args.ftp_user)
    ftp_passwd = str(args.ftp_passwd)
    remote_path = Path() if args.remote_path is None else Path(args.remote_path)
    # body
    with FTP(ftp_host, ftp_user, ftp_passwd) as ftp:
        ftp.dir(str(remote_path), logger.info)


def ftp_rename(args: Namespace) -> None:
    logger.debug("ftp_rename(args)")
    # arguments
    ftp_host = str(args.ftp_host)
    ftp_user = str(args.ftp_user)
    ftp_passwd = str(args.ftp_passwd)
    from_remote_path = Path(args.from_remote_path)
    to_remote_path = Path(args.to_remote_path)
    # body
    with FTP(ftp_host, ftp_user, ftp_passwd) as ftp:
        ftp.rename(str(from_remote_path), str(to_remote_path))


def ftp_install(args: Namespace) -> None:
    logger.debug("ftp_install(args)")
    # arguments
    http_url = str(args.http_url)
    ftp_host = str(args.ftp_host)
    ftp_user = str(args.ftp_user)
    ftp_passwd = str(args.ftp_passwd)
    elfinder_path = Path(args.elfinder_path)
    files_path = Path(args.files_path)
    title = str(args.title)
    favicon = str(args.favicon)
    # body
    with FTP(ftp_host, ftp_user, ftp_passwd) as ftp:
        # install elfinder from zip
        with as_file(files("free_uploader").joinpath("resources").joinpath("elFinder-2.1.61.zip")) as elfinder_file:
            with ZipFile(elfinder_file) as elfinder_zip:
                for zip_info in elfinder_zip.infolist():
                    zip_path = elfinder_path.joinpath(*Path(zip_info.filename).parts[1:])
                    if zip_info.is_dir():
                        logger.info(f"FTP mkd  {zip_path}")
                        try:
                            ftp.mkd(str(zip_path))
                        except error_perm:
                            pass
                    else:
                        logger.info(f"FTP stor {zip_path}")
                        with elfinder_zip.open(zip_info) as zip_file:
                            ftp.storbinary(f"STOR {zip_path}", zip_file)
        # create files directory
        logger.info(f"FTP mkd  {files_path}")
        try:
            ftp.mkd(str(files_path))
        except error_perm:
            pass
        # upload upload.php
        # TODO : create parents
        with as_file(files("free_uploader").joinpath("resources").joinpath("upload.php")) as upload_php_path:
            with open(upload_php_path, "rb") as upload_php_file:
                url_path = Path(urlparse(http_url).path)
                upload_path = Path(url_path).relative_to(url_path.root)
                logger.info(f"FTP stor {upload_path}")
                ftp.storbinary(f"STOR {upload_path}", upload_php_file)
        jinja2_env = Environment(loader=PackageLoader("free_uploader"))
        with BytesIO() as elfinder_io:
            elfinder_tpl = jinja2_env.get_template("elfinder.html.jinja2")
            elfinder_str = elfinder_tpl.render(title=title, favicon=favicon)
            elfinder_io.write(elfinder_str.encode())
            elfinder_io.seek(0)
            index_path = elfinder_path.joinpath("index.html")
            logger.info(f"FTP stor {index_path}")
            ftp.storbinary(f"STOR {index_path}", elfinder_io)
        with BytesIO() as connector_io:
            files_url = urlparse(http_url)._replace(path=str(files_path))
            logger.debug(f"files_url={files_url}")
            files_path = Path(*[".."] * (1 + len(elfinder_path.parts)), files_path)
            logger.debug(f"files_path={files_path}")
            #
            connector_tpl = jinja2_env.get_template("connector.minimal.php.jinja2")
            connector_str = connector_tpl.render(url=files_url.geturl(), path=str(files_path))
            connector_io.write(connector_str.encode())
            connector_io.seek(0)
            connector_path = elfinder_path.joinpath("php", "connector.minimal.php")
            logger.info(f"FTP stor {connector_path}")
            ftp.storbinary(f"STOR {connector_path}", connector_io)
        set_server_mode(ServerMode.DEFAULT, ftp)


def set_server_mode(mode: ServerMode, ftp: FTP) -> None:
    logger.debug(f"set_server_mode(mode={mode}, ftp=...)")
    with BytesIO(f"php{server_modes_php_versions[mode]} 1\n".encode()) as htaccess_io:
        htaccess_path = ".htaccess"
        logger.info(f"FTP stor {htaccess_path}")
        ftp.storbinary(f"STOR {htaccess_path}", htaccess_io)


def ftp_mode(args: Namespace) -> None:
    logger.debug("ftp_mode(args)")
    # arguments
    ftp_host = str(args.ftp_host)
    ftp_user = str(args.ftp_user)
    ftp_passwd = str(args.ftp_passwd)
    mode = ServerMode(args.mode)
    # body
    with FTP(ftp_host, ftp_user, ftp_passwd) as ftp:
        set_server_mode(mode, ftp)


def main(http_url: str, ftp_host: str, ftp_user: str, ftp_passwd: str) -> int:
    # argparse
    parser = ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.set_defaults(http_url=http_url, ftp_host=ftp_host, ftp_user=ftp_user, ftp_passwd=ftp_passwd)
    subparsers = parser.add_subparsers(required=True)

    # upload subcommand
    parser_upload = subparsers.add_parser("upload")
    parser_upload.add_argument("--chunk-size", default=DEFAULT_CHUNK_SIZE, type=int)
    parser_upload.add_argument("--max-try", default=DEFAULT_MAX_TRY, type=int)
    parser_upload.add_argument("--remote-file-path", type=Path)
    parser_upload.add_argument("file_to_upload", type=FileType("rb"))
    parser_upload.set_defaults(func=http_upload)

    # remove subcommand
    parser_remove = subparsers.add_parser("remove")
    parser_remove.add_argument("--dir", action="store_true")
    parser_remove.add_argument("remote_path", type=Path)
    parser_remove.set_defaults(func=ftp_remove)

    # list subcommand
    parser_list = subparsers.add_parser("list")
    parser_list.add_argument("remote_path", type=Path, nargs="?")
    parser_list.set_defaults(func=ftp_list)

    # rename subcommand
    parser_rename = subparsers.add_parser("rename")
    parser_rename.add_argument("from_remote_path", type=Path)
    parser_rename.add_argument("to_remote_path", type=Path)
    parser_rename.set_defaults(func=ftp_rename)

    # install
    parser_install = subparsers.add_parser("install")
    parser_install.add_argument("--title", default=DEFAULT_HTML_TITLE)
    parser_install.add_argument("--favicon", default=DEFAULT_HTML_FAVICON)
    parser_install.add_argument("--files-path", type=Path, default=DEFAULT_FILES_PATH)
    parser_install.add_argument("--elfinder-path", type=Path, default=DEFAULT_ELFINDER_PATH)
    parser_install.set_defaults(func=ftp_install)

    # mode
    parser_mode = subparsers.add_parser("mode")
    parser_mode.add_argument("mode", type=ServerMode, choices=ServerMode)
    parser_mode.set_defaults(func=ftp_mode)

    # parse args
    args = parser.parse_args()

    # logger
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    logger.debug(args)

    # args callback
    args.func(args)

    return EX_OK
