import QtQml
import Quickshell.Io

QtObject {
  id: root
  property string language: "ru"
  readonly property string locale: language === "system"
    ? (Qt.locale().name.toLowerCase().startsWith("ru") ? "ru" : "en")
    : (language === "ru" ? "ru" : "en")
  property var english: ({})
  property var russian: ({})

  function parse(source) {
    try {
      var parsed = JSON.parse(source)
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return ({})
      return parsed
    } catch (error) { return ({}) }
  }
  function text(key, values) {
    var selected = locale === "ru" ? russian : english
    var template = Object.prototype.hasOwnProperty.call(selected, key) ? selected[key]
      : Object.prototype.hasOwnProperty.call(english, key) ? english[key] : key
    return String(template).replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, function(match, name) {
      if (!values || !Object.prototype.hasOwnProperty.call(values, name)) return match
      var value = values[name]
      return typeof value === "string" || typeof value === "number" ? String(value) : match
    })
  }

  property FileView englishFile: FileView {
    path: root.localPath("en.json")
    blockLoading: false
    blockAllReads: false
    printErrors: false
    onLoaded: root.english = root.parse(text())
  }
  property FileView russianFile: FileView {
    path: root.localPath("ru.json")
    blockLoading: false
    blockAllReads: false
    printErrors: false
    onLoaded: root.russian = root.parse(text())
  }

  function localPath(file) {
    var url = String(Qt.resolvedUrl("locales/" + file))
    return url.indexOf("file:///") === 0 ? decodeURIComponent(url.slice(7)) : ""
  }
}
