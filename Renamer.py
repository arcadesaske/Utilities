#!/usr/bin/env python3
# Renamer.py

import os, sys, time
import re, regex
from datetime import datetime

# --- CONFIGURAZIONE E UTILS ---
LOG_FILE = "renamed.log"

PATTERN_EPISODE_NUM = re.compile(r'[sS](\d{2})[eE](\d{2})|(\d{1})x(\d{2})')
PATTERN_MOVIE = re.compile(r'^(.*?)(?:\s*\(?(\d{4})\)?)[._ -]?.*$', re.IGNORECASE)
PATTERN_ANIME = re.compile(r'^(.+?)(\d+)?_Ep_(\d+)', re.IGNORECASE)

_TAGS = r'(?:\d{3,4}p|WEB|ITA|ENG|BluRay|HDTV|HDRip|REPACK|WEBRip|AMZN|DDP|AAC|H\.264|x264|x265|MAX|DSNP|HEVC|Atmos|Dolby|10bit|7\.1|5\.1)'
_EP_TITLE = r'(?!' + _TAGS + r'\b)[A-Za-z0-9àòùìè,\'._ -…]+?(?<![._ -])(?=\s*\(|\s*\[|\s*[._ -]' + _TAGS + r'\b|\s*$)'

PATTERN_SERIES = regex.compile(
    r'^(?:\[.*?\]\s*)?(.+?)(?:[._ -](\d{4}))?[._ -]'
    r'(?|[sS](\d{1,2})[eE](\d{2,3})|(\d{1,2})x(\d{2,3}))'
    r'(?:[._ -]+(' + _EP_TITLE + r'))?',
    regex.IGNORECASE
)
def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def log_operation(old_name, new_name):
    timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {old_name} -> {new_name}\n")

def safe_rename(directory, old_name, new_name):
    if old_name == new_name:
        return False
    
    try:
        old_path = os.path.join(directory, old_name)
        new_path = os.path.join(directory, new_name)
        
        log_operation(old_name, new_name)
        os.rename(old_path, new_path)
        print(f"✔️ Renamed: {old_name} -> {new_name}")
        return True
    except OSError as e:
        print(f"❌ Error renaming {old_name}: {e}")
        return False

def format_string(text):
    if not text: return ""
    return text.replace('.', ' ').replace('_', ' ').replace('-', ' ').strip()

def split_camel_case(name):
    return re.sub(r'([a-z])([A-Z])', r'\1 \2', name)

def clean_anime_filename(filename):
    name, ext = os.path.splitext(filename)
    match = PATTERN_ANIME.match(name)
    if not match:
        return None

    raw_name = match.group(1)
    episode = match.group(3).zfill(2)
    anime_name = split_camel_case(raw_name).strip()

    if match.group(2) != None:
        season = match.group(2).zfill(2)
        return f"{anime_name} - s{season}e{episode} -{ext}"

    return f"{anime_name} - s01e{episode} -{ext}"

def rename_anime(directory):
    any_renamed = False
    for file in os.listdir(directory):
        if file.lower().endswith((".mp4", ".mkv")):
            new_name = clean_anime_filename(file)
            if new_name and safe_rename(directory, file, new_name):
                any_renamed = True

    if not any_renamed:
        print("No files were modified.")

def get_episode_info(filename):
    match = PATTERN_EPISODE_NUM.search(filename)
    if match:
        val = match.group(2) if match.group(1) else match.group(4)
        return int(val)
    return None

def clean_show_filename(filename):
    name, ext = os.path.splitext(filename)
    match = PATTERN_SERIES.match(name)
    if not match:
        return None

    series_name = format_string(match.group(1))
    series_year = match.group(2)
    season_num = match.group(3).zfill(2)
    ep_num = match.group(4).zfill(2)
    ep_title = format_string(match.group(5)) or f"Episode {ep_num}"

    year_str = f" ({series_year})" if series_year else ""
    return f"{series_name}{year_str} - s{season_num}e{ep_num} - {ep_title}{ext}"

def clean_movie_filename(filename):
    name, ext = os.path.splitext(filename)

    # Se il file ha un pattern da episodio (SxxEyy o 1x01), non è un film
    if PATTERN_EPISODE_NUM.search(name):
        return None

    match = PATTERN_MOVIE.match(name)
    if not match:
        return None

    title = format_string(match.group(1))
    year = match.group(2)
    
    if not year:
        year_search = re.search(r'\b(\d{4})\b', filename)
        year = year_search.group(1) if year_search else "Unknown"

    return f"{title} ({year}){ext}"

def rename_show(directory):
    mkv_map = {}
    srt_files = []
    any_renamed = False

    for file in os.listdir(directory):
        if file.lower().endswith(".mkv"):
            new_name = clean_show_filename(file)
            final_name = new_name if new_name else file
            
            if new_name and safe_rename(directory, file, new_name):
                any_renamed = True
            
            ep_id = get_episode_info(file)
            if ep_id is not None:
                mkv_map[ep_id] = final_name
        
        elif file.lower().endswith(".srt"):
            srt_files.append(file)

    for srt in srt_files:
        ep_id = get_episode_info(srt)
        if ep_id in mkv_map:
            new_srt_name = mkv_map[ep_id].rsplit('.', 1)[0] + ".it.srt"
            if safe_rename(directory, srt, new_srt_name):
                any_renamed = True

    if not any_renamed:
        print("No files were modified.")

def rename_movie(directory):
    any_renamed = False
    for file in os.listdir(directory):
        if file.lower().endswith(".mkv"):
            new_name = clean_movie_filename(file)
            if new_name and safe_rename(directory, file, new_name):
                any_renamed = True
    
    if not any_renamed:
        print("No files were modified.")

def show_pattern_fix(path):
    for root, _, files in os.walk(path):
        for file in files:
            if file.lower().endswith((".mkv", ".mp4")):
                new_name = PATTERN_EPISODE_NUM.sub(lambda x: x.group(0).lower(), file)
                safe_rename(root, file, new_name)

# --- MENU ---

def get_path():
    p = input("Enter directory path (Enter for current): ").strip()
    return p if p else os.getcwd()

def main():
    while True:
        print("\n" + "-"*30)
        print("|   MEDIA FILENAME RENAMER   |")
        print("-"*30)
        choice = input(
            "1. Rename TV Shows (MKV + SRT)\n"
            "2. Rename Movies\n"
            "3. Rename Anime\n"
            "4. Lowercase SE pattern\n"
            "5. Exit\n>> "
        )

        if choice == '1':
            rename_show(get_path())
        elif choice == '2':
            rename_movie(get_path())
        elif choice == '3':
            rename_anime(get_path())
        elif choice == '4':
            show_pattern_fix(get_path())
        elif choice == '5':
            print("Goodbye!")
            break
        else:
            print("Invalid choice.")

        print()
        print()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)