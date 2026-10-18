/* Iconițe pe grila de 24, cu linie (stroke = currentColor). Doar din lista asta: agentul alege un nume, nu SVG. */
window.VICONS = {
  bell: "M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15L6 16Z M10 20.5a2 2 0 0 0 4 0",
  plus: "M12 5v14 M5 12h14",
  link: "M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1 M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1",
  phone: "M8 3h8a1.5 1.5 0 0 1 1.5 1.5v15A1.5 1.5 0 0 1 16 21H8a1.5 1.5 0 0 1-1.5-1.5v-15A1.5 1.5 0 0 1 8 3Z M11 18h2",
  cart: "M3 4h2.2l2.3 11h10.4l2.1-8H6.4 M9.5 19.5a1 1 0 1 0 0 .01 M17 19.5a1 1 0 1 0 0 .01",
  check: "M5 12.5l4.5 4.5L19 7.5",
  star: "M12 3.8l2.5 5.1 5.6.8-4 4 1 5.6-5.1-2.7-5 2.7 1-5.6-4.1-4 5.6-.8L12 3.8Z",
  bolt: "M13 3L5 13.5h6L10 21l8-10.5h-6L13 3Z",
  chat: "M4.5 5.5h15v10h-9L6 19.5v-4H4.5v-10Z",
  play: "M8 5.5v13l10.5-6.5L8 5.5Z"
};
window.vIcon = function (name, size, parent) {
  var ns = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size); svg.setAttribute("height", size);
  svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.9"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  var p = document.createElementNS(ns, "path");
  p.setAttribute("d", window.VICONS[name] || window.VICONS.check);
  svg.appendChild(p);
  if (parent) parent.appendChild(svg);
  return svg;
};
