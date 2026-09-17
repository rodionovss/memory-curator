// Memory Curator: proactive knowledge delivery в OpenCode (ADR 002).
//
// На первое сообщение сессии плагин вызывает контракт `curator context` и
// добавляет ranked context cards в parts сообщения пользователя — до
// генерации ответа, без ручного вызова тулзов. Изоляция от storage:
// плагин знает только CLI/JSON контракт, не бэкенд. Любая ошибка
// глушится — сбой доставки не ломает сессию.
const deliveredSessions = new Set()

function _triggerOf(output) {
  const parts = output.parts ?? []
  const texts = parts
    .filter((p) => p && p.type === "text" && typeof p.text === "string")
    .map((p) => p.text)
  return texts.join("\n")
}

function _cardsToContext(json) {
  const cards = (json && json.cards) || []
  if (!cards.length) return null
  const lines = cards.map((c) => {
    const tags = Array.isArray(c.tags) ? c.tags.join(", ") : ""
    const file = c.source_file ? ` · полный текст: ${c.source_file} (curator get '${c.title}')` : ""
    return `- **${c.title}** [${c.score}] ${c.reason}\n  ${String(c.summary).trim().slice(0, 400)}${file}`
  })
  return [
    "## Знания из базы Memory Curator (proactive delivery)",
    "Эти проверенные факты автоматически подобраны под твою задачу. Учитывай их; полный текст — по source_file или curator get.",
    ...lines,
  ].join("\n")
}

export const CuratorContext = async ({ $ }) => {
  return {
    "chat.message": async (input, output) => {
      try {
        if (deliveredSessions.has(input.sessionID)) return

        const trigger = _triggerOf(output)
        if (!trigger.trim()) return

        const proc =
          await $`curator context ${trigger}`.quiet().nothrow()
        if (!proc.ok) return

        const json = JSON.parse(proc.stdout)
        const context = _cardsToContext(json)
        if (!context) return

        output.parts.push({
          type: "text",
          text:
            "\n\n---\n" +
            context +
            "\n(доставлено плагином Memory Curator; ручной fallback: curator get)",
        })
        deliveredSessions.add(input.sessionID)
      } catch {
        // ошибка retrieval → нет доставки, сессия продолжается
      }
    },
    event: async ({ event }) => {
      if (event.type === "session.deleted") {
        const id =
          event.properties?.info?.sessionID ?? event.properties?.sessionID
        if (id) deliveredSessions.delete(id)
      }
    },
  }
}
