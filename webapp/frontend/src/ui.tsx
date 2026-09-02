import { App as AntdApp, Button, Empty, Popconfirm, Select, Upload } from "antd";
import type { ButtonProps, UploadProps } from "antd";
import { LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function PrimaryButton(props: ButtonProps) {
  return <Button {...props} type="primary" />;
}

export function UploadButton(props: Omit<ButtonProps, "type"> & { type?: ButtonProps["type"]; accept?: string; multiple?: boolean; onFiles: (files: File[]) => void }) {
  const { accept, multiple, onFiles, type = "primary", ...buttonProps } = props;
  const beforeUpload: UploadProps["beforeUpload"] = (file) => {
    void onFiles([file as File]);
    return Upload.LIST_IGNORE;
  };
  return <Upload accept={accept} multiple={multiple} showUploadList={false} beforeUpload={beforeUpload} disabled={buttonProps.disabled}><Button {...buttonProps} type={type} /></Upload>;
}

export function AsyncButton(props: ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  const { loading = false, disabled, children, className, ...buttonProps } = props;
  return <button {...buttonProps} className={className} disabled={disabled || loading} aria-busy={loading || undefined}>
    {loading && <LoaderCircle className="zc-spin" size={14} aria-hidden="true" />}
    {children}
  </button>;
}

export const PAGE_RANGE_OPTIONS = ["1-4 页", "5-7 页", "8-10 页", "11-12 页", "13-15 页", "16-19 页", "20 页以上"];
export const DEFAULT_PAGE_RANGE = "8-10 页";

export function PageRangeSelect(props: { value?: string; onChange: (value: string) => void }) {
  return <Select
    className="kppt-page-range-select"
    popupClassName="kppt-page-range-select-dropdown"
    value={props.value || DEFAULT_PAGE_RANGE}
    onChange={props.onChange}
    options={PAGE_RANGE_OPTIONS.map((item) => ({ value: item, label: item }))}
    aria-label="页数范围"
  />;
}

export function AssetEmptyState(props: { title: string; description: string; action?: ReactNode; className?: string }) {
  const className = ["kppt-ant-empty", props.className].filter(Boolean).join(" ");
  return <div className={className}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span className="kppt-ant-empty-copy"><strong>{props.title}</strong><span>{props.description}</span></span>} />{props.action}</div>;
}

function noticeType(message: string): "success" | "error" | "warning" | "info" {
  if (/(失败|错误|无法|不可用|未能|没有变化)/.test(message)) return "error";
  if (/(请先|需要|将在后续|仍可继续)/.test(message)) return "warning";
  if (/(已|成功|正在)/.test(message)) return "success";
  return "info";
}

export function NoticeHost(props: { message: string; onClose: () => void }) {
  const { notification } = AntdApp.useApp();
  const lastMessage = useRef("");
  useEffect(() => {
    if (!props.message || props.message === lastMessage.current) return;
    lastMessage.current = props.message;
    const type = noticeType(props.message);
    const title = type === "success" ? "操作完成" : type === "error" ? "操作失败" : type === "warning" ? "请注意" : "提示";
    notification[type]({
      message: title,
      description: props.message,
      placement: "top",
      duration: type === "error" ? 5 : 3.5,
      pauseOnHover: true,
      className: "kppt-app-notification",
    });
    props.onClose();
  }, [notification, props]);
  useEffect(() => {
    if (!props.message) lastMessage.current = "";
  }, [props.message]);
  return null;
}

export function ConfirmAction(props: { title: string; description?: string; disabled?: boolean; onConfirm: () => void | Promise<void>; children: ReactNode }) {
  const [confirming, setConfirming] = useState(false);
  async function confirm(): Promise<void> {
    setConfirming(true);
    try { await props.onConfirm(); } finally { setConfirming(false); }
  }
  return <Popconfirm title={props.title} description={props.description} okText="确认" cancelText="取消" okButtonProps={{ danger: true, loading: confirming }} disabled={props.disabled || confirming} onConfirm={() => void confirm()}>{props.children}</Popconfirm>;
}
