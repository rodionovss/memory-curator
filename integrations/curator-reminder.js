// Memory Curator: напоминание свериться с базой знаний, когда сессия
// уходит в idle (ответ агента завершён). macOS-нотификация, один раз
// на сессию; любые ошибки глушатся — плагин не должен ломать opencode.
//
// osascript через node:child_process (не Bun shell): в Desktop-сборке
// OpenCode контекст плагина не содержит рабочего `$`.
import { execFile } from "node:child_process"

const seen = new Set()

function _notify() {
  return new Promise((resolve) => {
    execFile(
      "/usr/bin/osascript",
      ["-e", 'display notification "Если в сессии были проверенные уроки — /curator-save" with title "Memory Curator"'],
      { timeout: 10000 },
      () => resolve(), // не macOS или osascript недоступен — молча
    )
  })
}

export default async function CuratorReminder() {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      const id =
        event.properties?.sessionID ??
        event.properties?.session_id ??
        event.properties?.info?.sessionID
      if (id) {
        if (seen.has(id)) return
        seen.add(id)
      }
      try {
        await _notify()
      } catch {
        // не macOS или osascript недоступен — молча
      }
    },
  }
}
