'use strict';
(function () {

  /* ── State ─────────────────────────────────────────────────────────────── */
  var activeProject = null;
  var sidebarMode   = null;   // 'create' | 'choose' | 'view'
  var sidebarOpen   = false;

  try { activeProject = JSON.parse(localStorage.getItem('phasm_project') || 'null'); } catch(e) {}

  /* ── DOM bootstrap ─────────────────────────────────────────────────────── */
  var sidebar = document.getElementById('right-sidebar');
  var tab     = document.getElementById('sidebar-tab');
  if (!sidebar || !tab) return;

  tab.addEventListener('click', function() {
    if (sidebarOpen) closeSidebar();
    else {
      if (!sidebarMode) sidebarMode = 'view';
      renderSidebar();
      openSidebar();
    }
  });

  window.phasmSidebar = {
    open: function(mode) {
      sidebarMode = mode;
      renderSidebar();
      openSidebar();
    }
  };

  /* ── Open / close ──────────────────────────────────────────────────────── */
  function openSidebar() {
    sidebarOpen = true;
    sidebar.classList.add('open');
    document.body.classList.add('sidebar-open');
    tab.classList.add('open');
    tab.textContent = '\u276F';
    tab.title = 'Hide sidebar';
  }
  function closeSidebar() {
    sidebarOpen = false;
    sidebar.classList.remove('open');
    document.body.classList.remove('sidebar-open');
    tab.classList.remove('open');
    tab.textContent = '\u276E';
    tab.title = 'Show sidebar';
  }

  /* ── Render shell ──────────────────────────────────────────────────────── */
  function renderSidebar() {
    sidebar.textContent = '';

    var header = document.createElement('div');
    header.className = 'sb-header';
    var title = document.createElement('span');
    title.className = 'sb-title';
    title.textContent = sidebarMode === 'create' ? 'Create Project'
                      : sidebarMode === 'choose' ? 'Choose Project'
                      : 'View Project';
    header.appendChild(title);
    var closeBtn = document.createElement('button');
    closeBtn.className = 'sb-close-btn';
    closeBtn.textContent = '\u2715';
    closeBtn.addEventListener('click', closeSidebar);
    header.appendChild(closeBtn);
    sidebar.appendChild(header);

    if (activeProject) {
      var badge = document.createElement('div');
      badge.className = 'sb-active-badge';
      var dot = document.createElement('span'); dot.className = 'sb-active-dot';
      badge.appendChild(dot);
      badge.appendChild(document.createTextNode('Active: ' + activeProject.name));
      sidebar.appendChild(badge);
    }

    if (sidebarMode === 'create')      renderCreate();
    else if (sidebarMode === 'choose') renderChoose();
    else if (sidebarMode === 'view')   renderView();
  }

  /* ── Create Project ────────────────────────────────────────────────────── */
  function renderCreate() {
    var body = document.createElement('div');
    body.className = 'sb-body';
    body.appendChild(sbField('Project Name', 'sb-proj-name', 'text', 'My Project'));
    body.appendChild(sbField('Tags', 'sb-proj-tags', 'text', 'tag1, tag2'));

    var notesLbl = document.createElement('label');
    notesLbl.className = 'sb-label'; notesLbl.textContent = 'Notes';
    var notesArea = document.createElement('textarea');
    notesArea.id = 'sb-proj-notes'; notesArea.className = 'sb-textarea';
    notesArea.placeholder = 'Notes about this project...'; notesArea.rows = 4;
    body.appendChild(notesLbl); body.appendChild(notesArea);

    var saveBtn = document.createElement('button');
    saveBtn.className = 'sb-btn sb-btn-primary'; saveBtn.textContent = 'Save Project';
    saveBtn.addEventListener('click', function() {
      var name  = document.getElementById('sb-proj-name').value.trim();
      var tags  = document.getElementById('sb-proj-tags').value.trim();
      var notes = document.getElementById('sb-proj-notes').value.trim();
      if (!name) { sbAlert('Project name is required.'); return; }
      saveBtn.disabled = true; saveBtn.textContent = 'Saving...';
      fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, tags: tags, notes: notes })
      })
      .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(p) {
        activeProject = { id: p.id, name: p.name, tags: p.tags, notes: p.notes };
        localStorage.setItem('phasm_project', JSON.stringify(activeProject));
        sidebarMode = 'view'; renderSidebar();
        sbToast('Project "' + p.name + '" created and set as active.');
      })
      .catch(function(e) { saveBtn.disabled = false; saveBtn.textContent = 'Save Project'; sbAlert('Error: ' + e.message); });
    });
    body.appendChild(saveBtn);
    sidebar.appendChild(body);
  }

  /* ── Choose Project ────────────────────────────────────────────────────── */
  function renderChoose() {
    var body = document.createElement('div');
    body.className = 'sb-body';
    var list = document.createElement('div');
    list.className = 'sb-project-list'; list.textContent = 'Loading...';
    body.appendChild(list); sidebar.appendChild(body);

    fetch('/api/projects')
      .then(function(r) { return r.json(); })
      .then(function(projects) {
        list.textContent = '';
        if (!projects.length) {
          sbEmpty(list, 'No projects yet. Create one first.'); return;
        }
        projects.forEach(function(p) { list.appendChild(buildProjectCard(p)); });
      })
      .catch(function() { list.textContent = 'Failed to load projects.'; });
  }

  /* ── View Project ──────────────────────────────────────────────────────── */
  function renderView() {
    var body = document.createElement('div');
    body.className = 'sb-body';

    if (!activeProject) {
      sbEmpty(body, 'No active project. Use "Choose Project" to select one.');
      sidebar.appendChild(body); return;
    }

    var loading = document.createElement('div');
    loading.className = 'sb-empty'; loading.textContent = 'Loading...';
    body.appendChild(loading); sidebar.appendChild(body);

    fetch('/api/projects/' + activeProject.id)
      .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(res) {
        body.textContent = '';
        var p = res.project;

        /* project info card */
        var info = document.createElement('div'); info.className = 'sb-proj-info';
        var nameEl = document.createElement('div'); nameEl.className = 'sb-proj-info-name';
        nameEl.textContent = p.name; info.appendChild(nameEl);

        if (p.tags) {
          var tagsEl = document.createElement('div'); tagsEl.className = 'sb-proj-info-tags';
          p.tags.split(',').forEach(function(t) {
            t = t.trim(); if (!t) return;
            var chip = document.createElement('span'); chip.className = 'sb-tag-chip';
            chip.textContent = t; tagsEl.appendChild(chip);
          });
          info.appendChild(tagsEl);
        }
        if (p.notes) {
          var notesEl = document.createElement('div'); notesEl.className = 'sb-proj-info-notes';
          notesEl.textContent = p.notes; info.appendChild(notesEl);
        }
        var dateEl = document.createElement('div'); dateEl.className = 'sb-proj-info-date';
        dateEl.textContent = 'Created ' + fmtDate(p.created_at); info.appendChild(dateEl);

        var delBtn = document.createElement('button');
        delBtn.className = 'sb-btn sb-btn-danger'; delBtn.textContent = 'Delete Project';
        delBtn.addEventListener('click', function() {
          if (!confirm('Delete project "' + p.name + '" and all its data?')) return;
          fetch('/api/projects/' + p.id, { method: 'DELETE' }).then(function() {
            if (activeProject && activeProject.id === p.id) {
              activeProject = null; localStorage.removeItem('phasm_project');
            }
            sidebarMode = 'choose'; renderSidebar();
          });
        });
        info.appendChild(delBtn);
        body.appendChild(info);

        /* file tree grouped by source_type (folder) */
        var fileTitle = document.createElement('div');
        fileTitle.className = 'sb-section-title';
        fileTitle.textContent = 'Project Files';
        body.appendChild(fileTitle);

        if (!res.data.length) {
          sbEmpty(body, 'No files yet. Export data from a tool to create files.');
        } else {
          /* group by source_type */
          var folders = {};
          res.data.forEach(function(d) {
            var folder = d.source_type || 'Misc';
            if (!folders[folder]) folders[folder] = [];
            folders[folder].push(d);
          });

          Object.keys(folders).sort().forEach(function(folderName) {
            var folderEl = document.createElement('div');
            folderEl.className = 'sb-folder';

            var folderHdr = document.createElement('div');
            folderHdr.className = 'sb-folder-hdr';
            var folderIcon = document.createElement('span'); folderIcon.textContent = '\uD83D\uDCC1 ';
            var folderLbl  = document.createElement('span'); folderLbl.textContent = folderName;
            folderHdr.appendChild(folderIcon); folderHdr.appendChild(folderLbl);
            folderEl.appendChild(folderHdr);

            folders[folderName].forEach(function(d) {
              var isHtml = d.content && (
                d.content.trimStart().startsWith('<!DOCTYPE') ||
                d.content.trimStart().startsWith('<html')
              );
              var filename = (d.source_ref || 'untitled') + (isHtml ? '.html' : '.txt');
              var fileRow = document.createElement('div');
              fileRow.className = 'sb-file-row';
              var fileIcon = document.createElement('span'); fileIcon.textContent = '\uD83D\uDCDD ';
              var fileLbl  = document.createElement('span'); fileLbl.className = 'sb-file-name';
              fileLbl.textContent = filename;
              var delBtn2 = document.createElement('button');
              delBtn2.className = 'sb-file-del'; delBtn2.textContent = '\u2715';
              delBtn2.title = 'Delete file';
              delBtn2.addEventListener('click', function(e) {
                e.stopPropagation();
                if (!confirm('Delete "' + filename + '"?')) return;
                fetch('/api/projects/' + p.id + '/data/' + d.id, { method: 'DELETE' })
                  .then(function() { fileRow.remove(); })
                  .catch(function() { sbAlert('Delete failed.'); });
              });
              fileRow.appendChild(fileIcon); fileRow.appendChild(fileLbl); fileRow.appendChild(delBtn2);
              fileRow.addEventListener('click', function() { openEditor(d, p.id, filename); });
              folderEl.appendChild(fileRow);
            });

            body.appendChild(folderEl);
          });
        }
      })
      .catch(function(e) {
        body.textContent = '';
        sbEmpty(body, 'Could not load project: ' + e.message);
      });
  }

  /* ── Editor dispatcher ──────────────────────────────────────────────────── */
  function openEditor(dataEntry, projectId, filename) {
    var isHtml = dataEntry.content && (
      dataEntry.content.trimStart().startsWith('<!DOCTYPE') ||
      dataEntry.content.trimStart().startsWith('<html')
    );
    if (isHtml) openHtmlViewer(dataEntry, projectId, filename);
    else        openTextEditor(dataEntry, projectId, filename);
  }

  /* ── HTML viewer overlay ────────────────────────────────────────────────── */
  function openHtmlViewer(dataEntry, projectId, filename) {
    var overlay = document.createElement('div');
    overlay.className = 'editor-overlay';

    var panel = document.createElement('div');
    panel.className = 'editor-panel';

    /* header */
    var hdr = document.createElement('div');
    hdr.className = 'editor-hdr';
    var filenameLbl = document.createElement('span');
    filenameLbl.className = 'editor-filename'; filenameLbl.textContent = filename;
    var actions = document.createElement('div'); actions.className = 'editor-actions';

    var printBtn = document.createElement('button');
    printBtn.className = 'editor-print-btn'; printBtn.textContent = '\uD83D\uDDA8 Print to PDF';
    var delFileBtn = document.createElement('button');
    delFileBtn.className = 'editor-del-btn'; delFileBtn.textContent = '\uD83D\uDDD1 Delete';
    var closeBtn = document.createElement('button');
    closeBtn.className = 'editor-close-btn'; closeBtn.textContent = '\u2715 Close';

    actions.appendChild(printBtn); actions.appendChild(delFileBtn); actions.appendChild(closeBtn);
    hdr.appendChild(filenameLbl); hdr.appendChild(actions);
    panel.appendChild(hdr);

    /* iframe */
    var iframe = document.createElement('iframe');
    iframe.className = 'editor-iframe';
    var blob = new Blob([dataEntry.content], { type: 'text/html; charset=utf-8' });
    var blobUrl = URL.createObjectURL(blob);
    iframe.src = blobUrl;
    panel.appendChild(iframe);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    function closeViewer() { overlay.remove(); URL.revokeObjectURL(blobUrl); }

    printBtn.addEventListener('click', function() { iframe.contentWindow.print(); });
    closeBtn.addEventListener('click', closeViewer);
    overlay.addEventListener('click', function(e) { if (e.target === overlay) closeViewer(); });
    document.addEventListener('keydown', function escHandler(e) {
      if (e.key === 'Escape') { closeViewer(); document.removeEventListener('keydown', escHandler); }
    });
    delFileBtn.addEventListener('click', function() {
      if (!confirm('Delete "' + filename + '"? This cannot be undone.')) return;
      delFileBtn.disabled = true; delFileBtn.textContent = 'Deleting...';
      fetch('/api/projects/' + projectId + '/data/' + dataEntry.id, { method: 'DELETE' })
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function() {
          closeViewer();
          sbToast('"' + filename + '" deleted.');
          if (sidebarOpen && sidebarMode === 'view') renderSidebar();
        })
        .catch(function(e) {
          delFileBtn.disabled = false; delFileBtn.textContent = '\uD83D\uDDD1 Delete';
          sbAlert('Delete failed: ' + e.message);
        });
    });
  }

  /* ── Text editor overlay ────────────────────────────────────────────────── */
  function openTextEditor(dataEntry, projectId, filename) {
    var overlay = document.createElement('div');
    overlay.className = 'editor-overlay';

    var panel = document.createElement('div');
    panel.className = 'editor-panel';

    /* header */
    var hdr = document.createElement('div');
    hdr.className = 'editor-hdr';
    var filenameLbl = document.createElement('span');
    filenameLbl.className = 'editor-filename'; filenameLbl.textContent = filename;
    var actions = document.createElement('div'); actions.className = 'editor-actions';
    var saveBtn = document.createElement('button');
    saveBtn.className = 'editor-save-btn'; saveBtn.textContent = 'Save';
    var delFileBtn = document.createElement('button');
    delFileBtn.className = 'editor-del-btn'; delFileBtn.textContent = '\uD83D\uDDD1 Delete';
    var closeBtn = document.createElement('button');
    closeBtn.className = 'editor-close-btn'; closeBtn.textContent = '\u2715 Close';
    actions.appendChild(saveBtn); actions.appendChild(delFileBtn); actions.appendChild(closeBtn);
    hdr.appendChild(filenameLbl); hdr.appendChild(actions);
    panel.appendChild(hdr);

    /* textarea */
    var ta = document.createElement('textarea');
    ta.className = 'editor-textarea'; ta.value = dataEntry.content;
    ta.spellcheck = false;
    panel.appendChild(ta);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    ta.focus();

    function closeEditor() { overlay.remove(); }

    closeBtn.addEventListener('click', closeEditor);
    overlay.addEventListener('click', function(e) { if (e.target === overlay) closeEditor(); });
    document.addEventListener('keydown', function escHandler(e) {
      if (e.key === 'Escape') { closeEditor(); document.removeEventListener('keydown', escHandler); }
    });
    delFileBtn.addEventListener('click', function() {
      if (!confirm('Delete "' + filename + '"? This cannot be undone.')) return;
      delFileBtn.disabled = true; delFileBtn.textContent = 'Deleting...';
      fetch('/api/projects/' + projectId + '/data/' + dataEntry.id, { method: 'DELETE' })
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function() {
          closeEditor();
          sbToast('"' + filename + '" deleted.');
          if (sidebarOpen && sidebarMode === 'view') renderSidebar();
        })
        .catch(function(e) {
          delFileBtn.disabled = false; delFileBtn.textContent = '\uD83D\uDDD1 Delete';
          sbAlert('Delete failed: ' + e.message);
        });
    });
    saveBtn.addEventListener('click', function() {
      saveBtn.disabled = true; saveBtn.textContent = 'Saving...';
      fetch('/api/projects/' + projectId + '/data/' + dataEntry.id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: ta.value })
      })
      .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function() {
        dataEntry.content = ta.value;
        saveBtn.disabled = false; saveBtn.textContent = 'Saved \u2713';
        setTimeout(function() { saveBtn.textContent = 'Save'; }, 2000);
        sbToast('File saved.');
      })
      .catch(function(e) {
        saveBtn.disabled = false; saveBtn.textContent = 'Save';
        sbAlert('Save failed: ' + e.message);
      });
    });
  }

  /* ── Shared helpers ─────────────────────────────────────────────────────── */
  function buildProjectCard(p) {
    var card = document.createElement('div');
    card.className = 'sb-project-card';
    if (activeProject && activeProject.id === p.id) card.classList.add('active');

    var nameEl = document.createElement('div'); nameEl.className = 'sb-card-name';
    nameEl.textContent = p.name; card.appendChild(nameEl);
    if (p.tags) {
      var tagsEl = document.createElement('div'); tagsEl.className = 'sb-card-tags';
      tagsEl.textContent = p.tags; card.appendChild(tagsEl);
    }
    var meta = document.createElement('div'); meta.className = 'sb-card-meta';
    meta.textContent = fmtDate(p.created_at) + (p.data_count ? '  \u00b7  ' + p.data_count + ' file' + (p.data_count !== 1 ? 's' : '') : '');
    card.appendChild(meta);

    var selectBtn = document.createElement('button');
    selectBtn.className = 'sb-btn sb-btn-select' + (activeProject && activeProject.id === p.id ? ' active' : '');
    selectBtn.textContent = (activeProject && activeProject.id === p.id) ? 'Active' : 'Select';
    selectBtn.addEventListener('click', function() {
      activeProject = { id: p.id, name: p.name, tags: p.tags, notes: p.notes };
      localStorage.setItem('phasm_project', JSON.stringify(activeProject));
      sidebarMode = 'view'; renderSidebar();
      sbToast('Project "' + p.name + '" is now active.');
    });
    card.appendChild(selectBtn);
    return card;
  }

  function sbField(labelText, id, type, placeholder) {
    var wrap = document.createElement('div');
    var lbl = document.createElement('label'); lbl.className = 'sb-label'; lbl.textContent = labelText;
    var inp = document.createElement('input'); inp.id = id; inp.type = type;
    inp.className = 'sb-input'; inp.placeholder = placeholder || '';
    wrap.appendChild(lbl); wrap.appendChild(inp);
    return wrap;
  }

  function sbEmpty(parent, msg) {
    var el = document.createElement('div'); el.className = 'sb-empty'; el.textContent = msg;
    parent.appendChild(el);
  }

  function fmtDate(s) {
    if (!s) return '';
    try {
      var d = new Date(s.includes('T') || s.includes('Z') ? s : s.replace(' ', 'T') + 'Z');
      return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch(e) { return s; }
  }

  function sbAlert(msg) { alert(msg); }

  function sbToast(msg) {
    var t = document.getElementById('toast');
    if (!t) {
      t = document.createElement('div'); t.id = 'toast'; t.className = 'toast hidden';
      document.body.appendChild(t);
    }
    t.textContent = msg; t.className = 'toast ok';
    setTimeout(function() { t.className = 'toast hidden'; }, 3500);
  }

  /* ── Export pre-built HTML file to project (called from tools) ─────────── */
  window.phasmExportHtmlToProject = function(htmlContent, sourceType, sourceRef) {
    if (!activeProject) {
      sbAlert('No active project selected. Open Projects \u2192 Choose Project first.');
      return;
    }
    fetch('/api/projects/' + activeProject.id + '/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_type: sourceType || 'Misc',
        source_ref:  sourceRef  || 'export',
        content:     htmlContent
      })
    })
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function() {
      sbToast('Exported to "' + (sourceRef || 'export') + '.html" in "' + activeProject.name + '".');
      if (sidebarOpen && sidebarMode === 'view') renderSidebar();
    })
    .catch(function(e) { sbAlert('Export failed: ' + e.message); });
  };

  /* ── Export to project file (called from tools) ─────────────────────────── */
  window.phasmExportToProject = function(messages, sourceType, sourceRef) {
    if (!activeProject) {
      sbAlert('No active project selected. Open Projects \u2192 Choose Project first.');
      return;
    }
    // Build formatted content block
    var lines = messages.map(function(m) {
      return '--- ' + (m.source_ref || '') + ' ---\n' + m.content;
    });
    var content = lines.join('\n\n');

    fetch('/api/projects/' + activeProject.id + '/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_type: sourceType || 'Misc',
        source_ref:  sourceRef  || 'export',
        content: content
      })
    })
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function(res) {
      var fileLabel = sourceRef + '.txt';
      sbToast(messages.length + ' message' + (messages.length !== 1 ? 's' : '') +
        ' exported to ' + fileLabel + ' in "' + activeProject.name + '".');
      if (sidebarOpen && sidebarMode === 'view') renderSidebar();
    })
    .catch(function(e) { sbAlert('Export failed: ' + e.message); });
  };

}());
