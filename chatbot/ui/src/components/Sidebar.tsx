import { Edit3, Menu, MessageSquarePlus, PanelLeftClose, Trash2 } from "lucide-react";
import type { Conversation } from "../lib/types";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string;
  collapsed: boolean;
  mode: "fake" | "real";
  onToggle: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRename: (id: string) => void;
  onDelete: (id: string) => void;
}

export function Sidebar({
  conversations,
  activeId,
  collapsed,
  mode,
  onToggle,
  onNew,
  onSelect,
  onRename,
  onDelete,
}: SidebarProps) {
  return (
    <aside className={collapsed ? "sidebar sidebar--collapsed" : "sidebar"} aria-label="Hội thoại">
      <div className="sidebar__top">
        <button className="icon-button" onClick={onToggle} aria-label={collapsed ? "Mở thanh bên" : "Thu gọn thanh bên"}>
          {collapsed ? <Menu aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}
        </button>
        {!collapsed && <span className={`mode-badge mode-badge--${mode}`}>{mode === "fake" ? "Mô phỏng" : "Dữ liệu thật"}</span>}
      </div>
      <button className="new-chat-button" onClick={onNew} aria-label="Tạo hội thoại mới">
        <MessageSquarePlus aria-hidden="true" />
        {!collapsed && <span>Hội thoại mới</span>}
      </button>
      {!collapsed && (
        <nav className="conversation-list" aria-label="Danh sách hội thoại">
          {conversations.map((conversation) => (
            <div className={conversation.id === activeId ? "conversation-row conversation-row--active" : "conversation-row"} key={conversation.id}>
              <button className="conversation-row__select" onClick={() => onSelect(conversation.id)}>
                <span>{conversation.title}</span>
              </button>
              <button className="icon-button icon-button--small" onClick={() => onRename(conversation.id)} aria-label={`Đổi tên ${conversation.title}`}>
                <Edit3 aria-hidden="true" />
              </button>
              <button className="icon-button icon-button--small" onClick={() => onDelete(conversation.id)} aria-label={`Xóa ${conversation.title}`}>
                <Trash2 aria-hidden="true" />
              </button>
            </div>
          ))}
        </nav>
      )}
    </aside>
  );
}

