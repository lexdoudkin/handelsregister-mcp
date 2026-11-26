"""fetch_document's postback, against a fake browser (offline, no portal call)."""

from handelsregister_mcp.client import HandelsregisterClient

CONTROL = "ergebnissForm:selectedSuchErgebnisFormTable:0:j_idt227:0:fade_"


class _Form:
    def __init__(self):
        self.controls = {}

    def new_control(self, kind, name, attrs):
        self.controls[name] = attrs["value"]


class _Response:
    def read(self):
        return b"<?xml version='1.0'?><synthetic/>"

    def info(self):
        return {"Content-Type": "application/xml",
                "Content-Disposition": 'attachment;filename="synthetic.xml"'}


class _Browser:
    def __init__(self):
        self.form = None
        self.submitted = None

    def select_form(self, name):
        self.form = _Form()

    def submit(self, *args, **kwargs):
        self.submitted = dict(self.form.controls)
        return _Response()


def test_fetch_document_posts_only_the_link_id(tmp_path):
    client = HandelsregisterClient(download_dir=tmp_path)
    client.browser = _Browser()
    client._doc_controls = {0: {"UT": CONTROL}}

    result = client.fetch_document(0, "UT")

    # Like the browser's click: the link's own id, and no javax.faces.source.
    assert client.browser.submitted == {CONTROL: CONTROL}
    assert result["path"].endswith(".xml")
