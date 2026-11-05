# Q&A Analytics plugin

This plugin adds the **Q&A Analytics** page to the LangBot sidebar. The
**Overview**, **Questions**, and **Sessions** tabs show the Workspace's
knowledge-base questions, keyword cloud, frequent questions, and visitor
regions. The **Message board** tab lists visitor leads submitted from the
standalone consultation pages and lets staff mark them as processed. All views
can be filtered by the bots configured in the current Workspace.

The page asset and sidebar entry come from this plugin. Question collection,
lead storage, retention, and queries are implemented in LangBot Core, so a
plugin upgrade cannot change the analytics data model. The message board is
write-capable only through the status action (pending → processed); leads are
never deleted or edited from the page.

## Install

Package the directory contents (the directory itself must be the archive root)
and install the `.lbpkg` from **Add extension → Upload extension** in the WebUI:

```bash
cd plugins/qa-analytics
zip -r ../qa-analytics-0.1.2.lbpkg .
```

Choose **Manual add**, upload the `.lbpkg`, confirm the install, then enable the
plugin. The page appears under **Plugin pages** in the sidebar. A `.zip` upload
is treated as a Skill by the WebUI, so plugin packages must use `.lbpkg`.

## Configuration

Core configuration lives in `data/config.yaml`:

```yaml
qa_analytics:
  enabled: true
  retention_days: 90
  mask_ip: true
  word_cloud_sample_size: 500
  word_cloud_words: 100
  geoip:
    enabled: false
    database_path: ''
  page:
    plugin_author: 'langbot-team'
    plugin_name: 'qa-analytics'
  auto_cleanup:
    enabled: true
    check_interval_hours: 24
    batch_size: 1000
```

`page.plugin_author` / `page.plugin_name` must match this plugin's identity. If
you fork the plugin under another identity, update both values so Core serves
the page API data path for your package.
