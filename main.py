# FeedMe v2.0 20250414.07:40
import os
import json
import subprocess
import xml.etree.ElementTree as ET
import feedparser
import re
import html
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext, font, simpledialog
import my_logger
from my_logger import log_error, log_debug

SUBSCRIPTIONS_FILE = "subscriptions.json"
MAX_EPISODES = 100

def load_subscriptions():
    log_debug("Loading subscriptions.")
    if os.path.exists(SUBSCRIPTIONS_FILE):
        try:
            with open(SUBSCRIPTIONS_FILE, "r") as f:
                feeds = json.load(f)
                log_debug(f"Loaded {len(feeds)} feeds from {SUBSCRIPTIONS_FILE}.")
                return feeds
        except Exception as e:
            log_error(f"Error loading {SUBSCRIPTIONS_FILE}: {e}")
    else:
        log_debug(f"File {SUBSCRIPTIONS_FILE} does not exist, starting with empty subscriptions.")
    return {}

def truncate_episodes(feeds):
    log_debug("Truncating episodes if needed.")
    for feed_name, feed in feeds.items():
        episodes = feed.get("episodes", [])
        if len(episodes) > MAX_EPISODES:
            log_debug(f"'{feed_name}' has {len(episodes)} episodes; cut to {MAX_EPISODES}.")
            feed["episodes"] = episodes[:MAX_EPISODES]

def save_subscriptions(feeds):
    log_debug("Saving subscriptions.")
    truncate_episodes(feeds)
    try:
        with open(SUBSCRIPTIONS_FILE, "w") as f:
            json.dump(feeds, f, indent=2)
        log_debug(f"Subscriptions saved in {SUBSCRIPTIONS_FILE}.")
    except Exception as e:
        log_error(f"Error saving {SUBSCRIPTIONS_FILE}: {e}")

def import_opml(filepath):
    log_debug(f"Importing OPML from {filepath}.")
    feeds = {}
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        for body in root.findall("body"):
            for outline in body.iter("outline"):
                title = outline.attrib.get("title") or outline.attrib.get("text")
                feed_url = outline.attrib.get("xmlUrl")
                if title and feed_url:
                    feeds[title] = {"url": feed_url, "episodes": []}
                    log_debug(f"Imported '{title}' with URL: {feed_url}.")
    except Exception as e:
        log_error(f"Can't process OPML '{filepath}': {e}")
    log_debug(f"Imported {len(feeds)} feeds.")
    return feeds

def fetch_podcast(feed_url):
    log_debug(f"Fetching podcast feed: {feed_url}.")
    return feedparser.parse(feed_url)

def update_all_feeds(podcast_feeds):
    log_debug("Starting update of all feeds.")
    updated_feeds = {}
    for podcast_name, feed_info in podcast_feeds.items():
        feed_url = feed_info.get("url")
        log_debug(f"Updating '{podcast_name}' from URL: {feed_url}.")
        data = fetch_podcast(feed_url)
        if data.bozo:
            log_error(f"Feed error for '{podcast_name}': {data.bozo_exception}")
            updated_feeds[podcast_name] = feed_info
            continue

        old_episodes = {ep.get("link"): ep for ep in feed_info.get("episodes", [])}
        new_episodes = []
        log_debug(f"Found {len(data.entries)} entries for feed '{podcast_name}'.")
        for entry in data.entries:
            link = entry.get("link", "")
            read_status = old_episodes.get(link, {}).get("read", False)
            new_episode = {
                "title": entry.get("title", "No Title"),
                "published": entry.get("published", "No Publish Date"),
                "summary": entry.get("summary", "No Summary"),
                "link": link,
                "enclosures": entry.get("enclosures", []),
                "read": read_status
            }
            new_episodes.append(new_episode)
            log_debug(f"Processed episode: {new_episode['title']}, read: {read_status}")

        if len(new_episodes) > MAX_EPISODES:
            log_debug(f"Trimming '{podcast_name}' to {MAX_EPISODES} episodes.")
            new_episodes = new_episodes[:MAX_EPISODES]
        updated_feeds[podcast_name] = {"url": feed_url, "episodes": new_episodes}
        log_debug(f"Feed '{podcast_name}' updated with {len(new_episodes)} episodes.")
    log_debug("Feeds update complete.")
    return updated_feeds

def clean_html(raw_html):
    log_debug("Cleaning HTML content.")
    no_script = re.sub(r'(?is)<(script|style).*?>.*?(</\1>)', '', raw_html)
    no_tags = re.sub(r'<[^>]+>', '', no_script)
    clean_text = html.unescape(no_tags)
    clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)
    clean_text = re.sub(r'[ \t]+', ' ', clean_text)
    cleaned = clean_text.strip()
    log_debug("HTML cleaned.")
    return cleaned

class PodcastApp(tk.Tk):
    def __init__(self, podcasts):
        log_debug("Initializing PodcastApp.")
        super().__init__()
        self.title("FeedMe Podcasts Seymour!")
        try:
            icon = tk.PhotoImage(file="feed-me_icon.png")
            self.iconphoto(False, icon)
        except Exception as e:
            log_error(f"Failed to load icon: {e}")
        self.podcasts = podcasts
        self.current_podcast = None
        self.current_episode_index = None
        self.read_timer = None

        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(size=11)
        self.normal_font = default_font
        self.bold_font = default_font.copy()
        self.bold_font.configure(weight="bold")

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Treeview", background="black", foreground="white", fieldbackground="black", font=("TkDefaultFont", 11))
        style.map("Treeview", background=[("selected", "#347083")])

        self.create_widgets()

        self.bind("<Escape>", self.hide_context_menu)

        self.populate_podcast_list()
        log_debug("PodcastApp initialized.")

    def create_widgets(self):
        log_debug("Creating widgets for PodcastApp.")
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.left_frame = ttk.Frame(self.paned)
        self.paned.add(self.left_frame, weight=1)
        self.setup_left_frame()

        self.right_frame = ttk.Frame(self.paned)
        self.paned.add(self.right_frame, weight=3)
        self.setup_right_frame()

    def setup_left_frame(self):
        log_debug("Setting up left frame.")
        podcast_label = ttk.Label(self.left_frame, text="Podcasts:", font=self.bold_font)
        podcast_label.pack(pady=(10, 0))

        self.podcast_listbox = tk.Listbox(self.left_frame, bg="black", fg="white", font=("TkDefaultFont", 11))
        self.podcast_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.podcast_listbox.bind("<<ListboxSelect>>", self.on_podcast_select)
        self.podcast_listbox.bind("<Button-3>", self.show_context_menu)  # Right-click

        frame_buttons = ttk.Frame(self.left_frame)
        frame_buttons.pack(pady=(0, 10))
        ttk.Button(frame_buttons, text="Update Feeds", command=self.update_feeds).grid(row=0, column=0, padx=5)
        ttk.Button(frame_buttons, text="Import OPML", command=self.import_opml_file).grid(row=0, column=1, padx=5)
        ttk.Button(frame_buttons, text="Add Feed", command=self.add_new_feed).grid(row=0, column=2, padx=5)
        log_debug("Left frame set up complete.")

        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Delete Feed", command=self.delete_feed)

    def show_context_menu(self, event):
        try:
            index = self.podcast_listbox.nearest(event.y)
            self.podcast_listbox.selection_clear(0, tk.END)
            self.podcast_listbox.selection_set(index)
            self.podcast_listbox.activate(index)
            log_debug(f"Right-click on podcast list, index: {index}")
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def hide_context_menu(self, event):
        log_debug("Escape pressed; hiding context menu if visible.")
        try:
            self.context_menu.unpost()
        except Exception as e:
            log_error(f"Error hiding context menu: {e}")

    def delete_feed(self):
        selection = self.podcast_listbox.curselection()
        if not selection:
            log_error("Delete feed invoked with nothing selected.")
            return
        display_name = self.podcast_listbox.get(selection[0])
        podcast_name = display_name.rstrip(" *")
        answer = messagebox.askyesno("Delete Feed", f"Are you sure you wish to delete the feed '{podcast_name}' and all its episodes?")
        if answer:
            if podcast_name in self.podcasts:
                log_debug(f"Deleting feed: {podcast_name}.")
                del self.podcasts[podcast_name]
                save_subscriptions(self.podcasts)
                self.populate_podcast_list()
                self.clear_episode_details()
            else:
                log_error(f"Attempted to delete a feed that does not exist: {podcast_name}.")

    def setup_right_frame(self):
        log_debug("Setting up right frame.")
        self.episodes_details_frame = ttk.Frame(self.right_frame)
        self.episodes_details_frame.pack(fill=tk.BOTH, expand=True)

        self.episodes_frame = ttk.Frame(self.episodes_details_frame)
        self.episodes_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10,5))

        episodes_label = ttk.Label(self.episodes_frame, text="Episodes:", font=self.bold_font)
        episodes_label.pack(pady=(0, 5))
        columns = ("published", "title")
        self.episodes_tree = ttk.Treeview(self.episodes_frame, columns=columns, show="headings", selectmode="browse")
        self.episodes_tree.heading("published", text="Published")
        self.episodes_tree.heading("title", text="Title")
        self.episodes_tree.column("published", width=100)
        self.episodes_tree.column("title", width=400)
        self.episodes_tree.pack(fill=tk.BOTH, expand=True)
        self.episodes_tree.bind("<<TreeviewSelect>>", self.on_episode_select)
        self.episodes_tree.bind("<Double-Button-1>", self.view_episode_details)

        frame_mark = ttk.Frame(self.episodes_frame)
        frame_mark.pack(pady=5)
        ttk.Button(frame_mark, text="Mark as Read", command=self.manual_mark_read).grid(row=0, column=0, padx=5)
        ttk.Button(frame_mark, text="Mark as Unread", command=self.manual_mark_unread).grid(row=0, column=1, padx=5)

        self.details_frame = ttk.Frame(self.episodes_details_frame)
        self.details_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5,10))

        details_label = ttk.Label(self.details_frame, text="Episode Details:", font=self.bold_font)
        details_label.pack(pady=(0, 5))

        self.details_text = scrolledtext.ScrolledText(self.details_frame, wrap=tk.WORD, bg="black", fg="white", font=("TkDefaultFont", 11))
        self.details_text.pack(fill=tk.BOTH, expand=True)

        frame_control = ttk.Frame(self.details_frame)
        frame_control.pack(pady=(5, 10))
        ttk.Button(frame_control, text="Play It!", command=self.play_episode).grid(row=0, column=0, padx=5)
        ttk.Button(frame_control, text="Get It", command=self.download_episode).grid(row=0, column=1, padx=5)
        log_debug("Right frame set up complete.")

    def populate_podcast_list(self):
        log_debug("Populating podcast list in left frame.")
        self.podcast_listbox.delete(0, tk.END)
        for podcast in sorted(self.podcasts.keys()):
            episodes = self.podcasts[podcast].get("episodes", [])
            display_name = f"{podcast} *" if any(not ep.get("read", False) for ep in episodes) else podcast
            self.podcast_listbox.insert(tk.END, display_name)
        log_debug("Podcast list populated.")
        
    def download_episode(self):
        if self.current_podcast is None or self.current_episode_index is None:
            log_error("Download episode called with no selection.")
            messagebox.showwarning("No Selection", "Select an episode to download.")
            return
        
        podcast_name = self.current_podcast
        episodes = self.podcasts[podcast_name]["episodes"]
        
        if not episodes or self.current_episode_index >= len(episodes):
            log_error(f"Invalid episode index for {podcast_name}.")
            messagebox.showerror("Error", "No valid episode selected.")
            return
        
        currentEpisode = episodes[self.current_episode_index]
        enclosures = currentEpisode.get("enclosures", [])
        
        if not enclosures:
            log_error(f"No media found in this episode of {podcast_name}.")
            messagebox.showinfo("Info", "This episode has no downloadable content.")
            return
        
        media_url = enclosures[0].get('href', None)
        
        if not media_url:
            log_error(f"No media URL found in this episode of {podcast_name}.")
            messagebox.showerror("Error", "No valid media URL found.")
            return
        
        dir_path = filedialog.askdirectory(title="Select Download Location")
        if not dir_path:
            log_debug("User canceled download location selection.")
            return
        
        try:
            command = f'wget --output-document="{os.path.join(dir_path, os.path.basename(media_url))}" "{media_url}"'
            subprocess.Popen(command, shell=True)
            
            messagebox.showinfo("Download Started", f"Downloading {os.path.basename(media_url)} to {dir_path}.")
        except Exception as e:
            log_error(f"Error downloading file: {e}")
            messagebox.showerror("Download Error", f"Failed to start download. Reason: {str(e)}")

    def on_podcast_select(self, event):
        selection = self.podcast_listbox.curselection()
        if not selection:
            log_debug("No podcast selected.")
            return
        display_name = self.podcast_listbox.get(selection[0])
        podcast_name = display_name.rstrip(" *")
        log_debug(f"Selected podcast: {podcast_name}.")
        self.current_podcast = podcast_name
        self.populate_episode_list(podcast_name)
        self.clear_episode_details()

    def populate_episode_list(self, podcast_name):
        log_debug(f"Populating episodes list for podcast: {podcast_name}.")
        if self.read_timer:
            self.after_cancel(self.read_timer)
            self.read_timer = None
        self.episodes_tree.delete(*self.episodes_tree.get_children())
        feed_info = self.podcasts.get(podcast_name, {})
        episodes = feed_info.get("episodes", [])
        for idx, ep in enumerate(episodes):
            published = ep.get("published", "No Date")
            title = ep.get("title", "No Title")
            tag = "unread" if not ep.get("read", False) else "read"
            self.episodes_tree.insert("", "end", iid=str(idx), values=(published, title), tags=(tag,))
        self.episodes_tree.tag_configure("unread", font=self.bold_font)
        self.episodes_tree.tag_configure("read", font=self.normal_font)
        log_debug(f"Episode list for '{podcast_name}' populated with {len(episodes)} episodes.")

    def on_episode_select(self, event):
        selection = self.episodes_tree.selection()
        if not selection:
            log_debug("No episode selected.")
            return
        self.current_episode_index = int(selection[0])
        log_debug(f"Episode selected at index: {self.current_episode_index}.")
        if self.read_timer:
            self.after_cancel(self.read_timer)
        self.read_timer = self.after(100, self.mark_current_episode_as_read)
        self.view_episode_details()

    def mark_current_episode_as_read(self):
        if self.current_podcast is None or self.current_episode_index is None:
            log_debug("No current podcast or episode index for marking as read.")
            return
        episodes = self.podcasts[self.current_podcast]["episodes"]
        if self.current_episode_index < len(episodes):
            log_debug(f"Marking episode at index {self.current_episode_index} as read.")
            episodes[self.current_episode_index]["read"] = True
            self.update_episode_display(self.current_episode_index)
            save_subscriptions(self.podcasts)
            self.populate_podcast_list()
        else:
            log_error(f"Episode index {self.current_episode_index} out of range for podcast '{self.current_podcast}'.")
        self.read_timer = None

    def manual_mark_read(self):
        if self.current_podcast is None or self.current_episode_index is None:
            log_error("Manual mark read called with no episode selected.")
            messagebox.showwarning("No Selection", "Select a damn episode.")
            return
        log_debug(f"Manually marking episode at index {self.current_episode_index} as read.")
        self.podcasts[self.current_podcast]["episodes"][self.current_episode_index]["read"] = True
        self.update_episode_display(self.current_episode_index)
        save_subscriptions(self.podcasts)
        self.populate_podcast_list()

    def manual_mark_unread(self):
        if self.current_podcast is None or self.current_episode_index is None:
            log_error("Manual mark unread called with no episode selected.")
            messagebox.showwarning("No Selection", "Choose a damn podcast shithead.")
            return
        log_debug(f"Manually marking episode at index {self.current_episode_index} as unread.")
        self.podcasts[self.current_podcast]["episodes"][self.current_episode_index]["read"] = False
        self.update_episode_display(self.current_episode_index)
        save_subscriptions(self.podcasts)
        self.populate_podcast_list()

    def update_episode_display(self, index):
        episodes = self.podcasts[self.current_podcast]["episodes"]
        status = "unread" if not episodes[index].get("read", False) else "read"
        log_debug(f"Updating display for episode {index} with status: {status}.")
        self.episodes_tree.item(str(index), tags=(status,))

    def view_episode_details(self, event=None):
        if self.current_podcast is None or self.current_episode_index is None:
            log_debug("No episode selected for viewing details.")
            return
        episode = self.podcasts[self.current_podcast]["episodes"][self.current_episode_index]
        clean_summary = clean_html(episode.get("summary", "No Summary Available"))
        details = [
            f"Title: {episode.get('title', 'No Title')}",
            f"Published: {episode.get('published', 'No Publish Date')}",
            f"Link: {episode.get('link', 'No Link')}",
            "",
            "Summary:",
            clean_summary,
            ""
        ]
        enclosures = episode.get("enclosures", [])
        if enclosures:
            details.append("Media attachments:")
            for enc in enclosures:
                media_url = enc.get("href", "No URL")
                media_type = enc.get("type", "unknown type")
                details.append(f"   Type: {media_type} URL: {media_url}")
            log_debug("Episode details include media attachments.")
        else:
            details.append("No media attachments found.")
            log_debug("No media attachments found for this episode.")
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert(tk.END, "\n".join(details))
        log_debug("Episode details displayed.")

    def clear_episode_details(self):
        log_debug("Clearing episode details text area.")
        self.details_text.delete("1.0", tk.END)

    def play_episode(self):
        if self.current_podcast is None or self.current_episode_index is None:
            log_error("Play episode invoked with no episode selected.")
            messagebox.showwarning("No Selection", "Select a damn episode Idjit.")
            return
        episode = self.podcasts[self.current_podcast]["episodes"][self.current_episode_index]
        enclosures = episode.get("enclosures", [])
        if not enclosures:
            log_error("Attempted to play an episode with no media enclosures.")
            messagebox.showinfo("No media", "This episode has 0 media attachments, that's bullshit'.")
            return
        media_url = enclosures[0].get("href")
        if not media_url:
            log_error("Media URL missing in enclosure.")
            messagebox.showerror("Playback Error", "No valid media URL found.")
            return
        try:
            log_debug(f"Launching media player for URL: {media_url}.")
            subprocess.Popen(["mpv", "--force-window=yes", media_url])
        except Exception as e:
            log_error(f"Error launching mpv: {e}")
            messagebox.showerror("Playback Error", f"Error launching mpv: {e}")

    def update_feeds(self):
        log_debug("Update feeds button clicked.")
        self.podcasts = update_all_feeds(self.podcasts)
        save_subscriptions(self.podcasts)
        if self.current_podcast:
            self.populate_episode_list(self.current_podcast)
        self.populate_podcast_list()
        log_debug("Feeds updated successfully.")
        messagebox.showinfo("Feeds Updated", "Feeds Updated")

    def import_opml_file(self):
        log_debug("Import OPML file button clicked.")
        filename = filedialog.askopenfilename(title="Select OPML", filetypes=[("OPML files", "*.opml"), ("XML files", "*.xml"), ("All files", "*.*")])
        if not filename:
            log_debug("No file selected for OPML import.")
            return
        opml_feeds = import_opml(filename)
        if opml_feeds:
            for name, info in opml_feeds.items():
                if name in self.podcasts:
                    log_debug(f"Feed '{name}' already exists and will be overwritten from the imported data.")
                self.podcasts[name] = info
            save_subscriptions(self.podcasts)
            self.populate_podcast_list()
            log_debug(f"Imported {len(opml_feeds)} feeds from OPML.")
            messagebox.showinfo("Import Complete", f"Imported {len(opml_feeds)} feeds.")
        else:
            log_error("No feeds imported from OPML.")
            messagebox.showwarning("Import Failed")

    def add_new_feed(self):
        log_debug("Add new feed button clicked.")
        title = simpledialog.askstring("Add New Feed", "Enter podcast title:")
        if not title:
            log_debug("No title provided for new feed.")
            return
        url = simpledialog.askstring("Add New Feed", "Enter feed URL:")
        if not url:
            log_debug("No URL provided for new feed.")
            return
        if title in self.podcasts:
            log_error(f"Duplicate feed: {title}.")
            messagebox.showwarning("Duplicate Feed")
            return
        self.podcasts[title] = {"url": url, "episodes": []}
        save_subscriptions(self.podcasts)
        self.populate_podcast_list()
        log_debug(f"New feed '{title}' added.")
        messagebox.showinfo("Feed Added", f"'{title}'. Yippee!")

def main():
    log_debug("Starting main function.")
    feeds = load_subscriptions()
    app = PodcastApp(feeds)
    log_debug("Entering application mainloop.")
    app.mainloop()
    log_debug("Exiting application mainloop.")

if __name__ == "__main__":
    main()

