document.addEventListener("DOMContentLoaded", function() {
  if (window.renderMathInElement) {
    renderMathInElement(document.body, {
      delimiters: [
        {left: "$", right: "$", display: false},
        {left: "$$", right: "$$", display: true}
      ],
      throwOnError: false
    });
  }
});
