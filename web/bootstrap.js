(() => {
  const publishedUrl = 'https://mikawa-insar.pages.dev/';
  const explain = (state, message, isError = false) => {
    const connection = document.getElementById('connection');
    const notice = document.getElementById('notice');
    connection.textContent = state;
    notice.replaceChildren(document.createTextNode(message + ' '));
    if (isError) notice.classList.add('error');
    const link = document.createElement('a');
    link.href = publishedUrl;
    link.textContent = '公開画面を開く';
    notice.append(link);
  };

  // Classic scripts can run from file://; module scripts and JSON fetch cannot.
  // Do not attempt to load the application until it has an HTTP(S) origin.
  if (window.location.protocol === 'file:') {
    explain('公開画面へ移動', '最新データを表示する公開画面へ移動しています。移動しない場合はリンクを開いてください。');
    window.location.replace(publishedUrl);
    return;
  }

  import('./app.js').catch(() => {
    explain('読み込みエラー', '画面を読み込めませんでした。再読み込みするか、公開画面を開いてください。', true);
  });
})();
