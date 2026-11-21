function youtubeVideoId(address) {
  if (!address) return null;
  const url = new URL(address);
  if (url.origin !== "https://www.youtube.com") return null;
  const id = url.pathname === "/watch"
    ? url.searchParams.get("v")
    : /^\/shorts\/([^/]+)\/?$/.exec(url.pathname)?.[1];
  return id && /^[\w-]{11}$/.test(id) ? id : null;
}
