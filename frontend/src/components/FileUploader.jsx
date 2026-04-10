import { useState, useRef } from "react";

// 지원 확장자 및 MIME 타입
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".hwp", ".hwpx"];
const ACCEPTED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/x-hwp",
  "application/haansofthwp",
  "application/vnd.hancom.hwpx",
];

function isAcceptedFile(file) {
  if (!file) return false;
  if (ACCEPTED_MIME_TYPES.includes(file.type)) return true;
  // 일부 환경에서 MIME이 비어있는 경우 확장자로 폴백
  const name = file.name?.toLowerCase() || "";
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function getFileLabel(file) {
  const name = file.name?.toLowerCase() || "";
  if (name.endsWith(".docx")) return "DOCX";
  if (name.endsWith(".pdf")) return "PDF";
  if (name.endsWith(".hwp")) return "HWP";
  if (name.endsWith(".hwpx")) return "HWPX";
  return "FILE";
}

export default function FileUploader({ onFileSelect, disabled }) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const inputRef = useRef(null);

  function handleDrag(e) {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (isAcceptedFile(file)) {
      setSelectedFile(file);
      onFileSelect(file);
    }
  }

  function handleChange(e) {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      onFileSelect(file);
    }
  }

  return (
    <div
      className={`file-uploader ${dragActive ? "drag-active" : ""} ${disabled ? "disabled" : ""}`}
      onDragEnter={handleDrag}
      onDragLeave={handleDrag}
      onDragOver={handleDrag}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_EXTENSIONS.join(",")}
        onChange={handleChange}
        style={{ display: "none" }}
        disabled={disabled}
      />
      {selectedFile ? (
        <div className="file-info">
          <div className="file-icon-box">{getFileLabel(selectedFile)}</div>
          <div className="file-details">
            <span className="file-name">{selectedFile.name}</span>
            <span className="file-size">
              {(selectedFile.size / 1024 / 1024).toFixed(1)} MB
            </span>
          </div>
        </div>
      ) : (
        <div className="upload-placeholder">
          <div className="upload-icon-circle">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </div>
          <p className="upload-main-text">PDF·DOCX·HWP 파일을 드래그하거나 클릭하여 업로드</p>
          <p className="upload-hint">계약서 파일을 업로드하면 유형을 자동 감지합니다</p>
        </div>
      )}
    </div>
  );
}
