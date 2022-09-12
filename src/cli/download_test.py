import yt_dlp

URL = ""
COOKIE_FILE = ""


def main():
    ydl_config = {"noplaylist": True, "cookiefile": COOKIE_FILE}
    with yt_dlp.YoutubeDL(ydl_config) as ydl:
        extract_info = ydl.extract_info(URL, download=False)

    print(extract_info)


if __name__ == "__main__":
    main()
