/* Chart wrapper: builds Chart.js charts from <canvas data-chart="<json-script id>"> using design-token colours. */
(function () {
  var root = document.documentElement;
  var charts = [];

  function token(name) {
    return getComputedStyle(root).getPropertyValue("--" + name).trim();
  }

  function colorize(type, dataset) {
    var copy = Object.assign({}, dataset);
    if (dataset.colors) {
      copy.backgroundColor = dataset.colors.map(token);
      copy.borderColor = token("surface");
    } else {
      var color = token(dataset.color || "primary");
      copy.borderColor = color;
      copy.backgroundColor = type === "radar" ? token("primary-soft") : color;
      copy.pointBackgroundColor = color;
    }
    return copy;
  }

  function build(canvas) {
    var data = JSON.parse(document.getElementById(canvas.getAttribute("data-chart")).textContent);
    var muted = token("muted");
    var grid = token("border");
    var radial = data.type === "radar";
    var round = data.type === "doughnut";
    var scale = { ticks: { color: muted }, grid: { color: grid }, angleLines: { color: grid } };
    var options = {
      responsive: true,
      maintainAspectRatio: false,
      animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : undefined,
      plugins: { legend: { labels: { color: muted } } },
    };
    if (radial) {
      options.scales = { r: Object.assign({ pointLabels: { color: muted } }, scale) };
    } else if (!round) {
      options.scales = { x: scale, y: Object.assign({ beginAtZero: true }, scale) };
    }
    if (data.scale && options.scales) {
      Object.assign(options.scales[radial ? "r" : "y"], data.scale);
    }
    charts.push(
      new Chart(canvas, {
        type: data.type,
        data: { labels: data.labels, datasets: data.datasets.map(function (dataset) {
            return colorize(data.type, dataset);
          }) },
        options: options,
      })
    );
  }

  function buildAll() {
    charts.forEach(function (chart) {
      chart.destroy();
    });
    charts = [];
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    document.querySelectorAll("canvas[data-chart]").forEach(build);
  }

  buildAll();
  new MutationObserver(buildAll).observe(root, { attributes: true, attributeFilter: ["class"] });
})();
