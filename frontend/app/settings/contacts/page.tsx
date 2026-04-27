import { redirect } from "next/navigation";

/** 구 북마크 호환: 메인 내비 `/contacts`로 통일 */
export default function SettingsContactsRedirectPage() {
  redirect("/contacts");
}
