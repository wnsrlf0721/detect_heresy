const SITE = "http://localhost:3000";

function resultUrl(id) {
  return SITE + "/result?analysis=" + encodeURIComponent(id);
}
