import React, { useCallback, useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { createLearningGoal, getLearningProgressMap, GoalMap, LearningGoal } from '../api/learning'
import {
  KbFile,
  LIBRARY_KB_NAME,
  createKnowledgeBase,
  deleteKbFile,
  fetchKbFilePreview,
  getKbInfo,
  listKbFiles,
  listKnowledgeBases,
  retryKb,
  uploadFilesToKb,
} from '../api/knowledge'
import { PRODUCT_NAME } from './brand'

type IconSvgProps = { name: string; size?: number }
const PageIcon: React.FC<IconSvgProps> = ({ name, size = 16 }) => {
  const s = { width: size, height: size }
  switch (name) {
    case 'code':
      return <svg {...s} viewBox="0 0 36 36" fill="none"><path d="M19.649 5.39976C19.8701 4.51583 20.766 3.97857 21.65 4.19957C22.5339 4.42066 23.0712 5.31654 22.8502 6.20054L16.3502 32.2005C16.1291 33.0845 15.2332 33.6217 14.3492 33.4007C13.4653 33.1796 12.928 32.2837 13.149 31.3998L19.649 5.39976ZM7.15389 11.0668C7.83499 10.4617 8.87769 10.5235 9.48299 11.2044C10.0881 11.8855 10.0271 12.9282 9.34627 13.5336L6.13241 16.39C4.68932 17.6729 4.68937 19.9274 6.13241 21.2103L9.34627 24.0668C10.0271 24.6721 10.088 25.7148 9.48299 26.3959C8.87768 27.0769 7.835 27.1387 7.15389 26.5336L3.94002 23.6771C1.02 21.0815 1.01999 16.5188 3.94002 13.9232L7.15389 11.0668ZM26.5162 11.2044C27.1216 10.5234 28.1652 10.4613 28.8463 11.0668L32.0592 13.9232C34.8878 16.4376 34.9765 20.7982 32.3248 23.4281L32.0592 23.6771L28.8463 26.5336C28.1652 27.139 27.1216 27.077 26.5162 26.3959C25.9111 25.7147 25.9729 24.672 26.6539 24.0668L29.8668 21.2103C31.3098 19.9274 31.3099 17.6729 29.8668 16.39L26.6539 13.5336C25.9729 12.9282 25.9111 11.8855 26.5162 11.2044Z" fill="currentColor"/></svg>
    case 'showcase_app':
      return <svg {...s} viewBox="0 0 18 18" fill="currentColor"><path d="M11.7327 1.85156C12.8718 1.85156 13.7952 2.77498 13.7952 3.91406V14.4141C13.7952 15.5532 12.8718 16.4766 11.7327 16.4766H5.73267C4.59362 16.4765 3.67017 15.5531 3.67017 14.4141V3.91406C3.67017 2.77501 4.59362 1.85161 5.73267 1.85156H11.7327ZM5.73267 2.97656C5.21494 2.97661 4.79517 3.39633 4.79517 3.91406V14.4141C4.79517 14.9318 5.21494 15.3515 5.73267 15.3516H11.7327C12.2504 15.3516 12.6702 14.9318 12.6702 14.4141V3.91406C12.6702 3.3963 12.2504 2.97656 11.7327 2.97656H10.2288C10.2093 3.29028 9.95164 3.53891 9.63306 3.53906H7.83228C7.51377 3.53881 7.256 3.29023 7.23657 2.97656H5.73267ZM9.67017 12.9141C9.98083 12.9141 10.2327 13.1659 10.2327 13.4766C10.2327 13.7872 9.98083 14.0391 9.67017 14.0391H7.79517C7.48455 14.039 7.23267 13.7872 7.23267 13.4766C7.23267 13.1659 7.48455 12.9141 7.79517 12.9141H9.67017Z"/></svg>
    case 'showcase_project':
      return <svg {...s} viewBox="0 0 18 18" fill="currentColor"><g clipPath="url(#clip0_project)"><path d="M9.12891 1.6875C9.67582 1.68755 10.2002 1.90526 10.5869 2.29199L14.208 5.91309C14.5948 6.29984 14.8124 6.82417 14.8125 7.37109V13.5C14.8125 15.0533 13.5533 16.3125 12 16.3125H6C4.44671 16.3125 3.1875 15.0533 3.1875 13.5V4.5C3.1875 2.9467 4.4467 1.6875 6 1.6875H9.12891ZM6 2.8125C5.06802 2.8125 4.3125 3.56802 4.3125 4.5V13.5C4.3125 14.432 5.06802 15.1875 6 15.1875H12C12.932 15.1875 13.6875 14.432 13.6875 13.5V7.37109C13.6875 7.35147 13.6858 7.33197 13.6846 7.3125H11.25C10.1109 7.3125 9.1875 6.38908 9.1875 5.25V2.81543C9.16803 2.8142 9.14853 2.8125 9.12891 2.8125H6ZM11.625 12.1875C11.9357 12.1875 12.1875 12.4393 12.1875 12.75C12.1875 13.0607 11.9357 13.3125 11.625 13.3125H6.75C6.43934 13.3125 6.1875 13.0607 6.1875 12.75C6.1875 12.4393 6.43934 12.1875 6.75 12.1875H11.625ZM9 9.1875C9.31066 9.1875 9.5625 9.43934 9.5625 9.75C9.5625 10.0607 9.31066 10.3125 9 10.3125H6.75C6.43934 10.3125 6.1875 10.0607 6.1875 9.75C6.1875 9.43934 6.43934 9.1875 6.75 9.1875H9ZM10.3125 5.25C10.3125 5.76777 10.7322 6.1875 11.25 6.1875H12.8926L10.3125 3.60742V5.25Z"/></g><defs><clipPath id="clip0_project"><path d="M0 0H18V18H0z"/></clipPath></defs></svg>
    case 'showcase_game':
      return <svg {...s} viewBox="0 0 18 18" fill="currentColor"><path d="M14.5625 5.0625C14.5625 4.16503 13.835 3.4375 12.9375 3.4375H5.0625C4.16504 3.4375 3.4375 4.16504 3.4375 5.0625V12.9375C3.4375 13.835 4.16503 14.5625 5.0625 14.5625H12.9375C13.835 14.5625 14.5625 13.835 14.5625 12.9375V5.0625ZM15.8125 12.9375C15.8125 14.5254 14.5254 15.8125 12.9375 15.8125H5.0625C3.47469 15.8125 2.1875 14.5254 2.1875 12.9375V5.0625C2.1875 3.47468 3.47468 2.1875 5.0625 2.1875H12.9375C14.5254 2.1875 15.8125 3.47469 15.8125 5.0625V12.9375Z"/><path d="M10.7614 11.8182C10.7614 11.2345 11.2345 10.7614 11.8182 10.7614C12.4018 10.7614 12.875 11.2345 12.875 11.8182C12.875 12.4018 12.4018 12.875 11.8182 12.875C11.2345 12.875 10.7614 12.4018 10.7614 11.8182ZM7.94318 9C7.94318 8.41635 8.41635 7.94318 9 7.94318C9.58365 7.94318 10.0568 8.41635 10.0568 9C10.0568 9.58365 9.58365 10.0568 9 10.0568C8.41635 10.0568 7.94318 9.58365 7.94318 9ZM5.125 6.18182C5.125 5.59815 5.59815 5.125 6.18182 5.125C6.76548 5.125 7.23864 5.59815 7.23864 6.18182C7.23864 6.76548 6.76548 7.23864 6.18182 7.23864C5.59815 7.23864 5.125 6.76548 5.125 6.18182Z"/></svg>
    case 'showcase_tools':
      return <svg {...s} viewBox="0 0 18 18" fill="currentColor"><path d="M14.5649 5.13184C14.5649 4.19502 13.8055 3.43555 12.8687 3.43555H5.13135C4.19454 3.43555 3.43506 4.19503 3.43506 5.13184V12.8691C3.43506 13.806 4.19453 14.5654 5.13135 14.5654H12.8687C13.8055 14.5654 14.5649 13.806 14.5649 12.8691V5.13184ZM15.8149 12.8691C15.8149 14.4963 14.4959 15.8154 12.8687 15.8154H5.13135C3.50419 15.8154 2.18506 14.4964 2.18506 12.8691V5.13184C2.18506 3.50467 3.50418 2.18555 5.13135 2.18555H12.8687C14.4959 2.18555 15.8149 3.50468 15.8149 5.13184V12.8691Z"/><path d="M5.18257 5.55806C5.42665 5.31398 5.82326 5.31398 6.06734 5.55806L7.37984 6.87056C7.62391 7.11464 7.62391 7.51125 7.37984 7.75532L6.06734 9.06782C5.82326 9.3119 5.42665 9.3119 5.18257 9.06782C4.93849 8.82375 4.93849 8.42714 5.18257 8.18306L6.05269 7.31294L5.18257 6.44282C4.93849 6.19875 4.93849 5.80214 5.18257 5.55806Z"/></svg>
    case 'spaces':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="m8 1.9 5.2 2.95L8 7.8 2.8 4.85 8 1.9Z"/><path d="m2.8 8.3 5.2 2.95 5.2-2.95"/><path d="m2.8 11.6 5.2 2.95 5.2-2.95"/></svg>
    case 'plus':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M8 3v10M3 8h10"/></svg>
    case 'close':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 4l8 8M12 4l-8 8"/></svg>
    case 'search':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2"><circle cx="7" cy="7" r="5"/><path d="M11 11l3.5 3.5"/></svg>
    case 'github':
      return <svg {...s} viewBox="0 0 16 16" fill="currentColor"><path d="M7.99992 1.30029C11.6833 1.30029 14.6666 4.28363 14.6666 7.96696C14.6662 9.36379 14.2278 10.7253 13.4131 11.86C12.5984 12.9946 11.4484 13.8452 10.1249 14.292C9.79158 14.3586 9.66658 14.1503 9.66658 13.9753C9.66658 13.7503 9.67492 13.0336 9.67492 12.142C9.67492 11.517 9.46659 11.117 9.22492 10.9086C10.7083 10.742 12.2666 10.1753 12.2666 7.61696C12.2666 6.88363 12.0083 6.29196 11.5833 5.82529C11.6499 5.65863 11.8833 4.97529 11.5166 4.05863C11.5166 4.05863 10.9583 3.87529 9.68325 4.74196C9.14992 4.59196 8.58325 4.51696 8.01659 4.51696C7.44992 4.51696 6.88325 4.59196 6.34992 4.74196C5.07492 3.88363 4.51659 4.05863 4.51659 4.05863C4.14992 4.97529 4.38325 5.65863 4.44992 5.82529C4.02492 6.29196 3.76659 6.89196 3.76659 7.61696C3.76659 10.167 5.31659 10.742 6.79992 10.9086C6.60825 11.0753 6.43325 11.367 6.37492 11.8003C5.99159 11.9753 5.03325 12.2586 4.43325 11.2503C4.30825 11.0503 3.93325 10.5586 3.40825 10.567C2.84992 10.5753 3.18325 10.8836 3.41659 11.0086C3.69992 11.167 4.02492 11.7586 4.09992 11.9503C4.23325 12.3253 4.66659 13.042 6.34159 12.7336C6.34159 13.292 6.34992 13.817 6.34992 13.9753C6.34992 14.1503 6.22492 14.3503 5.89159 14.292C4.56378 13.85 3.40886 13.0011 2.59066 11.8658C1.77246 10.7305 1.33252 9.36638 1.33325 7.96696C1.33325 4.28363 4.31659 1.30029 7.99992 1.30029Z"/></svg>
    case 'disk':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M2.95801 11.5C2.95807 11.6876 3.03246 11.8682 3.16504 12.001C3.29774 12.1337 3.47836 12.2088 3.66602 12.209H12.333C12.5208 12.209 12.7012 12.1337 12.834 12.001C12.9667 11.8682 13.041 11.6877 13.041 11.5V7.13379H2.95801V11.5ZM8.67383 8.82031C9.08785 8.82054 9.42383 9.15624 9.42383 9.57031C9.4237 9.98428 9.08777 10.3201 8.67383 10.3203H8.66699C8.25286 10.3203 7.91712 9.98441 7.91699 9.57031C7.91699 9.1561 8.25278 8.82031 8.66699 8.82031H8.67383ZM11.0068 8.82031C11.421 8.8204 11.7568 9.15616 11.7568 9.57031C11.7567 9.98436 11.4209 10.3202 11.0068 10.3203H11C10.5859 10.3203 10.2501 9.98441 10.25 9.57031C10.25 9.1561 10.5858 8.82031 11 8.82031H11.0068ZM4.72852 3.79883C4.63154 3.81249 4.53795 3.84648 4.4541 3.89844C4.34224 3.96788 4.25097 4.06763 4.19238 4.18555L4.19141 4.1875L3.34082 5.88379H12.6582L11.8076 4.1875L11.8066 4.18555C11.748 4.06762 11.6578 3.96788 11.5459 3.89844C11.4618 3.84632 11.3678 3.81244 11.2705 3.79883L11.1729 3.79199H4.82715L4.72852 3.79883Z"/></svg>
    case 'down':
      return <svg {...s} viewBox="0 0 16 16" fill="currentColor"><path d="M10.2249 6.22429C10.469 5.98059 10.8647 5.98048 11.1087 6.22429C11.3528 6.46837 11.3528 6.86498 11.1087 7.10905L9.14876 9.06804C8.51414 9.70255 7.48548 9.70261 6.8509 9.06804L4.89094 7.10905C4.64687 6.86498 4.64687 6.46837 4.89094 6.22429C5.13502 5.98021 5.53163 5.98021 5.77571 6.22429L7.73469 8.18425C7.88112 8.33067 8.1185 8.3306 8.26497 8.18425L10.2249 6.22429Z"/></svg>
    case 'plugin':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M4 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z"/><path d="M8 4v8M4 8h8"/></svg>
    case 'chevron-left':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 4l-4 4 4 4"/></svg>
    case 'download':
      return <svg {...s} viewBox="0 0 16 16" fill="currentColor"><path d="M8 2.5C8.27614 2.5 8.5 2.72386 8.5 3V9.37868L10.4394 7.43934C10.6344 7.24435 10.9402 7.24435 11.1352 7.43934C11.3302 7.63432 11.3302 7.9401 11.1352 8.13508L8.56091 10.7094C8.36593 10.9044 8.06015 10.9044 7.86517 10.7094L5.29091 8.13508C5.09593 7.9401 5.09593 7.63432 5.29091 7.43934C5.48589 7.24435 5.79167 7.24435 5.98665 7.43934L7.92606 9.37868V3C7.92606 2.72386 8.14992 2.5 8.42606 2.5H8ZM3.5 12.5C3.5 12.2239 3.72386 12 4 12H12C12.2761 12 12.5 12.2239 12.5 12.5V13.5C12.5 13.7761 12.2761 14 12 14H4C3.72386 14 3.5 13.7761 3.5 13.5V12.5Z"/></svg>
    default:
      return null
  }
}

/* ============ NewTaskPage ============ */
export function NewTaskPage({ composer, sidebarBar }: { composer: React.ReactNode; sidebarBar?: React.ReactNode }) {
  return (
    <>
      <header className="header-x7rPuS">
        {sidebarBar && <div className="headerLeft-rH3lhm">{sidebarBar}</div>}
        <div className="headerCenter-cba9zB"></div>
        <div className="headerRight-QHfr9M"></div>
      </header>
      <div className="workspace-sBvxKr" style={{ ['--input-center-offset' as any]: '331px' }}>
        <div className="welcomeTitleWrapper-WfrDR6">
          <div className="traeWorkTitle-NJggA3">
            <div className="animationContainer-umIyNq" style={{ opacity: 1 }}>
              <div className="mainTextContainer-pXscK4">
                <span className="icon-rzUsCL" style={{ opacity: 1 }}>
                  <PageIcon name="code" size={36} />
                </span>
                <span className="titleText-H3MNV2 codeText-Lcyw9U" style={{ opacity: 1, transform: 'translateX(5px)' }}>Learn</span>
                <span className="withTraeText-dLQCwg" style={{ width: 'auto', opacity: 1 }}>
                  <span className="withTraeInner-hAXYMl">with {PRODUCT_NAME}</span>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="homeMessageInput-bhe4cx">
          {composer}
        </div>
        <div className="showcaseWrapper-kvK9FF" style={{ opacity: 1, transform: 'none' }}>
          <div className="showcaseSection-pTXHyZ">
            <div className="chipContainer-Wo8qmB">
              <div className="chip-Fx63TH"><span className="chipIcon-AN8sSU"><PageIcon name="showcase_app" size={16} /></span><span className="chipText-YMz4j8">应用开发</span></div>
              <div className="chip-Fx63TH"><span className="chipIcon-AN8sSU"><PageIcon name="showcase_project" size={16} /></span><span className="chipText-YMz4j8">项目理解</span></div>
              <div className="chip-Fx63TH"><span className="chipIcon-AN8sSU"><PageIcon name="showcase_game" size={16} /></span><span className="chipText-YMz4j8">游戏创意</span></div>
              <div className="chip-Fx63TH"><span className="chipIcon-AN8sSU"><PageIcon name="showcase_tools" size={16} /></span><span className="chipText-YMz4j8">工具脚本</span></div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

const WORK_PPT_SUB = ['经验分享', '活动复盘', '商业计划'] as const

export function WorkHomePage({ composer, sidebarBar }: { composer: React.ReactNode; sidebarBar?: React.ReactNode }) {
  const [pptOpen, setPptOpen] = useState(false)
  return (
    <>
      <header className="header-x7rPuS">
        {sidebarBar && <div className="headerLeft-rH3lhm">{sidebarBar}</div>}
        <div className="headerCenter-cba9zB" />
        <div className="headerRight-QHfr9M">
        </div>
      </header>
      <div className="workspace-sBvxKr" style={{ ['--input-center-offset' as any]: '331px' }}>
        <div className="welcomeTitleWrapper-WfrDR6">
          <div className="traeWorkTitle-NJggA3">
            <div className="animationContainer-umIyNq" style={{ opacity: 1 }}>
              <div className="mainTextContainer-pXscK4">
                <span className="icon-rzUsCL" style={{ opacity: 1 }}>
                  <PageIcon name="plugin" size={36} />
                </span>
                <span className="titleText-H3MNV2 codeText-Lcyw9U" style={{ opacity: 1, transform: 'translateX(5px)' }}>Work</span>
                <span className="withTraeText-dLQCwg" style={{ width: 'auto', opacity: 1 }}>
                  <span className="withTraeInner-hAXYMl">with TRAE</span>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="homeMessageInput-bhe4cx">{composer}</div>
        <div className="showcaseWrapper-kvK9FF" style={{ opacity: 1, transform: 'none' }}>
          <div className="showcaseSection-pTXHyZ">
            <div className="chipContainer-Wo8qmB">
              <div
                className="chip-Fx63TH"
                onMouseEnter={() => setPptOpen(true)}
              >
                <span className="chipIcon-AN8sSU"><PageIcon name="showcase_app" size={16} /></span>
                <span className="chipText-YMz4j8">生成 PPT</span>
              </div>
              <div className="chip-Fx63TH">
                <span className="chipIcon-AN8sSU"><PageIcon name="showcase_project" size={16} /></span>
                <span className="chipText-YMz4j8">数据分析</span>
              </div>
              <div className="chip-Fx63TH">
                <span className="chipIcon-AN8sSU"><PageIcon name="showcase_tools" size={16} /></span>
                <span className="chipText-YMz4j8">深度研究</span>
              </div>
              <div className="chip-Fx63TH">
                <span className="chipIcon-AN8sSU"><PageIcon name="showcase_game" size={16} /></span>
                <span className="chipText-YMz4j8">生成文档</span>
              </div>
            </div>
            {pptOpen && (
              <div className="workChipSubRow">
                <span className="workChipSubTitle">生成 PPT</span>
                <button type="button" className="workChipSubClose" aria-label="关闭" onClick={() => setPptOpen(false)}>×</button>
                <div className="workChipSubItems">
                  {WORK_PPT_SUB.map((label) => (
                    <span key={label} className="workChipSubItem">{label}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

const DESIGN_CARDS = [
  { title: '设计还原', desc: '设计还原：上传 UI 参考截图，还原同款电商详情页' },
  { title: '概念成稿', desc: '概念成稿：一句话描述想法，直出完整小程序原型' },
  { title: '规范出图', desc: '规范出图：对齐设计规范，产出高保真 SaaS 系统' },
] as const

export function DesignHomePage({ composer, sidebarBar }: { composer: React.ReactNode; sidebarBar?: React.ReactNode }) {
  return (
    <>
      <header className="header-x7rPuS">
        {sidebarBar && <div className="headerLeft-rH3lhm">{sidebarBar}</div>}
        <div className="headerCenter-cba9zB" />
        <div className="headerRight-QHfr9M">
        </div>
      </header>
      <div className="workspace-sBvxKr" style={{ ['--input-center-offset' as any]: '331px' }}>
        <div className="welcomeTitleWrapper-WfrDR6">
          <div className="traeWorkTitle-NJggA3">
            <div className="animationContainer-umIyNq" style={{ opacity: 1 }}>
              <div className="mainTextContainer-pXscK4">
                <span className="icon-rzUsCL" style={{ opacity: 1 }}>
                  <PageIcon name="plugin" size={36} />
                </span>
                <span className="titleText-H3MNV2 codeText-Lcyw9U" style={{ opacity: 1, transform: 'translateX(5px)' }}>Design</span>
                <span className="withTraeText-dLQCwg" style={{ width: 'auto', opacity: 1 }}>
                  <span className="withTraeInner-hAXYMl">with TRAE</span>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="homeMessageInput-bhe4cx">{composer}</div>
        <div className="showcaseWrapper-kvK9FF" style={{ opacity: 1 }}>
          <div className="designCardRow">
            {DESIGN_CARDS.map((card) => (
              <div key={card.title} className="designCard">
                <div className="designCardPreview" aria-hidden />
                <div className="designCardTitle">{card.title}</div>
                <div className="designCardDesc">{card.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

export function ModeShellPage({ title, sidebarBar }: { title: string; sidebarBar?: React.ReactNode }) {
  return (
    <div className="contentWrapper-U1GjQr">
      <header className="header-x7rPuS">
        {sidebarBar && <div className="headerLeft-rH3lhm">{sidebarBar}</div>}
        <div className="headerCenter-cba9zB" />
        <div className="headerRight-QHfr9M" />
      </header>
      <div className="workspace-sBvxKr">
        <div className="welcomeTitleWrapper-WfrDR6">
          <div className="traeWorkTitle-NJggA3">
            <span className="titleText-H3MNV2">{title}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

const headerBtnBase: React.CSSProperties = {
  alignItems: 'center',
  borderRadius: '6px',
  cursor: 'pointer',
  display: 'inline-flex',
  fontSize: '14px',
  gap: '4px',
  height: '32px',
  justifyContent: 'center',
  lineHeight: '20px',
  padding: '0 12px',
}

/* ============ Learning Space (学习空间) ============ */
const STAGE_LABELS: Record<string, string> = {
  diagnostic: '摸底诊断',
  explain: '讲解中',
  feynman_check: '理解检查',
  practice: '练习中',
  error_diagnosis: '纠错中',
  review: '复习中',
  completed: '已完成',
}

const ACTION_LABELS: Record<string, string> = {
  answer_pending: '回答待批改的问题',
  review: '间隔复习',
  probe: '先测一测，可跳过已掌握内容',
  practice: '继续练习',
  assess: '检验理解',
  complete: '空间已完成',
}

// Backend policy reasons are authored in English; map the known templates to
// learner-facing Chinese so "为什么现在学这个" reads naturally.
const REASON_LABELS: Record<string, string> = {
  answer_pending: '有一个问题等你作答，回答后我会批改并继续。',
  review: '这个知识点到了间隔复习时间，复习防止遗忘。',
  probe: '这个知识点还没学过，先测一测能否直接跳过。',
  practice: '这个知识点还没达到掌握线，继续练习直到达标。',
  assess: '需要你用自己的话解释这个概念，确认真正理解。',
  complete: '空间内所有知识点都已掌握。',
}

interface LearningSpacePageProps {
  goals: LearningGoal[]
  loading: boolean
  error: string
  onContinueLearning: (goal: LearningGoal) => void
  onCreateGoal: (title: string, description?: string) => void
  onRenameGoal: (bookId: string, title: string) => void
  onDeleteGoal: (bookId: string) => void
  sidebarBar?: React.ReactNode
}

export function LearningSpacePage({
  goals,
  loading,
  error,
  onContinueLearning,
  onCreateGoal,
  onRenameGoal,
  onDeleteGoal,
  sidebarBar,
}: LearningSpacePageProps) {
  const [selectedGoal, setSelectedGoal] = useState<LearningGoal | null>(null)
  const [creating, setCreating] = useState(false)
  const [renaming, setRenaming] = useState<LearningGoal | null>(null)
  const [menuFor, setMenuFor] = useState<string | null>(null)

  // Dismiss the open card menu on outside click / Escape (mirrors app-wide useDismiss).
  useEffect(() => {
    if (!menuFor) return
    let lastPointer = 0
    const isInside = (el: Node | null) => {
      const menu = document.querySelector(`[data-space-menu="${menuFor}"]`)
      const trigger = document.querySelector(`[data-space-more="${menuFor}"]`)
      return !!el && ((menu?.contains(el) ?? false) || (trigger?.contains(el) ?? false))
    }
    const close = () => setMenuFor(null)
    const onPointer = (e: PointerEvent) => {
      lastPointer = Date.now()
      if (!isInside(e.target as Node)) close()
    }
    // Synthetic clicks may only dispatch mouse events; dedupe against pointerdown.
    const onMouse = (e: MouseEvent) => {
      if (Date.now() - lastPointer < 50) return
      if (!isInside(e.target as Node)) close()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('mousedown', onMouse)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('mousedown', onMouse)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuFor])

  return (
    <div className="root-Bkr7v6">
      {sidebarBar && (
        <header className="header-x7rPuS">
          <div className="headerLeft-rH3lhm">{sidebarBar}</div>
          <div className="headerCenter-cba9zB" />
          <div className="headerRight-QHfr9M" />
        </header>
      )}
      <div className="scrollArea-fvGujy">
        <div className="scrollContent-Q7fN_Z">
          <div className="headerRail-GfhRry">
            <div className="titleGroup-R6DD_m">
              <h1 className="title-yQrHui">学习空间</h1>
              <p className="subtitle-Gi_Tjb">创建学习空间，Lumen 会为每个空间制定学习计划并跟踪掌握进度。</p>
            </div>
            <div className="headerActions-TKXare" style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                className="button-muTeiY primary-ZG2S1H large-psSWuL"
                style={{
                  ...headerBtnBase,
                  background: 'var(--bg-bg-invert)',
                  border: 'none',
                  color: 'var(--text-text-onaccent)',
                }}
                onClick={() => setCreating(true)}
              >
                <PageIcon name="plus" size={14} />
                <span>新建空间</span>
              </button>
            </div>
          </div>
          <div className="contentRail-dRMjXS">
            <div className="container-YgYmSM">
              {loading && (
                <p className="learningSpaceHint" style={{ color: 'var(--text-text-secondary)', fontSize: 13 }}>
                  正在加载学习空间…
                </p>
              )}
              {!loading && error && (
                <div className="learningSpaceError" style={{
                  border: '1px solid var(--status-error-default, #f65a5a)',
                  borderRadius: 8, padding: '12px 16px',
                  color: 'var(--status-error-default, #f65a5a)', fontSize: 13, marginBottom: 12,
                }}>
                  {error}
                </div>
              )}
              {!loading && !error && goals.length === 0 && (
                <div className="learningSpaceEmpty" style={{ textAlign: 'center', padding: '48px 0', color: 'var(--text-text-secondary)' }}>
                  <p style={{ fontSize: 14, marginBottom: 8 }}>还没有学习空间</p>
                  <p style={{ fontSize: 13 }}>点击「新建空间」开始，导入资料后由 Lumen 帮你制定学习计划。</p>
                </div>
              )}
              {goals.map((goal) => {
                const stageLabel = STAGE_LABELS[goal.current_stage] || goal.current_stage
                const mastery = Math.max(0, Math.min(100, Math.round(goal.avg_mastery_pct || 0)))
                return (
                  <div
                    key={goal.book_id}
                    className="spaceCard"
                    onClick={() => setSelectedGoal(goal)}
                  >
                    <div className="spaceCardHeader">
                      <span className="spaceCardIcon">
                        <PageIcon name="spaces" size={20} />
                      </span>
                      <div className="spaceCardBody">
                        <span className="spaceCardName">{goal.name || goal.book_id}</span>
                        <span className="spaceCardDesc">
                          {goal.description || (goal.goal_name ? '学习空间 · 等待制定学习计划' : '学习进度')}
                        </span>
                      </div>
                    </div>
                    <div className="spaceCardProgress">
                      <span className="spaceCardProgressBar">
                        <span
                          className="spaceCardProgressFill"
                          style={{ width: `${mastery}%` }}
                          aria-hidden
                        />
                      </span>
                      <span className="spaceCardProgressPct">掌握 {mastery}%</span>
                    </div>
                    <div className="spaceCardMeta">
                      <span className={`spaceCardStage${goal.current_stage === 'completed' ? ' isCompleted' : ''}`}>{stageLabel}</span>
                      <span>{goal.kp_count > 0 ? `${goal.kp_count} 个知识点` : '计划未生成'}</span>
                    </div>
                    <div className="spaceCardActions">
                      <button
                        type="button"
                        className="spaceCardBtnPrimary"
                        onClick={(e) => {
                          e.stopPropagation()
                          onContinueLearning(goal)
                        }}
                      >
                        继续学习
                      </button>
                      <button
                        type="button"
                        aria-label="更多操作"
                        className="spaceCardBtnMore"
                        data-space-more={goal.book_id}
                        onClick={(e) => {
                          e.stopPropagation()
                          setMenuFor((cur) => (cur === goal.book_id ? null : goal.book_id))
                        }}
                      >
                        <PageIcon name="down" size={14} />
                      </button>
                      {menuFor === goal.book_id && (
                        <div className="spaceCardMenu" role="menu" data-space-menu={goal.book_id}>
                          <button type="button" role="menuitem" style={goalMenuBtnStyle} onClick={(e) => { e.stopPropagation(); setRenaming(goal); setMenuFor(null) }}>重命名</button>
                          <button type="button" role="menuitem" style={{ ...goalMenuBtnStyle, color: 'var(--status-error-default, #f65a5a)' }} onClick={(e) => { e.stopPropagation(); onDeleteGoal(goal.book_id); setMenuFor(null) }}>删除</button>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>
      {selectedGoal && (
        <GoalDetailModal
          goal={selectedGoal}
          onClose={() => setSelectedGoal(null)}
          onContinueLearning={() => {
            setSelectedGoal(null)
            onContinueLearning(selectedGoal)
          }}
        />
      )}
      {creating && (
        <CreateGoalModal
          onClose={() => setCreating(false)}
          onCreate={(title, description) => {
            setCreating(false)
            onCreateGoal(title, description)
          }}
        />
      )}
      {renaming && (
        <RenameGoalModal
          goal={renaming}
          onClose={() => setRenaming(null)}
          onRename={(title) => {
            setRenaming(null)
            onRenameGoal(renaming.book_id, title)
          }}
        />
      )}
    </div>
  )
}

const goalMenuBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  borderRadius: 4,
  color: 'var(--text-text-default)',
  cursor: 'pointer',
  display: 'block',
  fontSize: 13,
  height: 28,
  lineHeight: '20px',
  padding: '0 10px',
  textAlign: 'left',
  width: '100%',
}

function GoalDetailModal({
  goal,
  onClose,
  onContinueLearning,
}: {
  goal: LearningGoal
  onClose: () => void
  onContinueLearning: () => void
}) {
  const [map, setMap] = useState<GoalMap | null>(null)
  const [mapError, setMapError] = useState('')

  useEffect(() => {
    let cancelled = false
    getLearningProgressMap(goal.book_id)
      .then((data) => { if (!cancelled) setMap(data) })
      .catch(() => { if (!cancelled) setMapError('无法加载进度，请稍后重试') })
    return () => { cancelled = true }
  }, [goal.book_id])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const goalCounts = map?.map.goal
  const counts = map?.map.counts
  const next = map?.next
  const progressPct = goalCounts && goalCounts.total > 0
    ? Math.round((goalCounts.mastered / goalCounts.total) * 100)
    : 0
  const actionLabel = (next && ACTION_LABELS[next.action]) || (next ? next.action : '')
  const nextTopic = next?.knowledge_point_name || next?.module_name || ''

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()} style={{ width: '520px', height: 'auto' }}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailTitleGroup-cpT99c">
              <h2 className="detailTitle-X7zIZu">{goal.name || goal.book_id}</h2>
              <p className="detailDescription-kBy0Ek">学习空间 · 进度详情</p>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div style={{ padding: '4px 20px 20px', color: 'var(--text-text-secondary)', fontSize: 14, lineHeight: '22px' }}>
            {mapError && <p style={{ color: 'var(--status-error-default, #f65a5a)', fontSize: 13 }}>{mapError}</p>}
            {!map && !mapError && <p>正在加载进度…</p>}
            {map && goalCounts && (
              <>
                <div className="goalDetailProgress" style={{ marginBottom: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
                    <span style={{ color: 'var(--text-text-default)' }}>空间整体进度</span>
                    <span>{goalCounts.mastered} / {goalCounts.total} 已掌握（{progressPct}%）</span>
                  </div>
                  <div className="goalProgressTrack" style={{ position: 'relative', display: 'inline-block', width: '100%', height: 8, borderRadius: 4, background: 'var(--bg-bg-overlay-l1)' }}>
                    <span
                      className="goalProgressFill"
                      style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${progressPct}%`, borderRadius: 4, background: 'var(--bg-bg-invert)' }}
                      aria-hidden
                    />
                  </div>
                </div>
                {goalCounts.total === 0 ? (
                  <div style={{ border: '1px solid var(--border-border-neutral-l2)', borderRadius: 8, padding: '12px 16px', marginBottom: 12 }}>
                    <p style={{ color: 'var(--text-text-default)', fontSize: 14, fontWeight: 500, marginBottom: 4 }}>学习计划尚未生成</p>
                    <p style={{ fontSize: 13 }}>点击「继续学习」，Lumen 会根据这个空间帮你制定学习计划并开始教学。</p>
                  </div>
                ) : map.map.complete ? (
                  <div style={{ border: '1px solid var(--border-border-neutral-l2)', borderRadius: 8, padding: '12px 16px', marginBottom: 12 }}>
                    <p style={{ color: 'var(--text-text-default)', fontSize: 14, fontWeight: 500, marginBottom: 4 }}>🎉 空间已完成</p>
                    <p style={{ fontSize: 13 }}>所有知识点均已掌握，无待复习内容。可以开始新的学习空间。</p>
                  </div>
                ) : (
                  next && (
                    <div style={{ border: '1px solid var(--border-border-neutral-l2)', borderRadius: 8, padding: '12px 16px', marginBottom: 12 }}>
                      <p style={{ color: 'var(--text-text-default)', fontSize: 14, fontWeight: 500, marginBottom: 4 }}>下一步：{actionLabel}</p>
                      <p style={{ fontSize: 13, marginBottom: 4 }}>{nextTopic ? `正在学习：${nextTopic}` : ''}</p>
                      <p style={{ fontSize: 12, color: 'var(--text-text-secondary)' }}>{REASON_LABELS[next.action] || next.reason}</p>
                      {next.action !== 'complete' && next.knowledge_point_name && (
                        <p style={{ fontSize: 12, marginTop: 6, color: 'var(--text-text-secondary)' }}>
                          掌握度 {Math.round((next.mastery ?? 0) * 100)}%（阈值 {Math.round((next.threshold ?? 0) * 100)}%）
                        </p>
                      )}
                    </div>
                  )
                )}
                {counts && (
                  <div style={{ display: 'flex', gap: 16, fontSize: 12, marginBottom: 12 }}>
                    <span>未开始 <b style={{ color: 'var(--text-text-default)' }}>{counts.new}</b></span>
                    <span>学习中 <b style={{ color: 'var(--text-text-default)' }}>{counts.learning}</b></span>
                    <span>已掌握 <b style={{ color: 'var(--text-text-default)' }}>{counts.mastered}</b></span>
                    {map.map.due_reviews > 0 && <span>待复习 <b style={{ color: 'var(--status-warning-default, #e8a23d)' }}>{map.map.due_reviews}</b></span>}
                  </div>
                )}
                {map.map.modules.length > 0 && (
                  <div style={{ fontSize: 13 }}>
                    {map.map.modules.map((mod) => (
                      <div key={mod.id} style={{ marginBottom: 10 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ color: 'var(--text-text-default)' }}>{mod.name}</span>
                          <span style={{ color: 'var(--text-text-secondary)' }}>{mod.mastered} / {mod.total}</span>
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {mod.knowledge_points.map((kp) => (
                            <span
                              key={kp.id}
                              title={`${kp.name}（${kp.status}，掌握 ${Math.round(kp.mastery * 100)}%）`}
                              style={{
                                display: 'inline-block',
                                width: 10,
                                height: 10,
                                borderRadius: 3,
                                background: kp.status === 'mastered'
                                  ? 'var(--status-success-default, #25b14c)'
                                  : kp.status === 'learning'
                                    ? 'var(--status-warning-default, #e8a23d)'
                                    : 'var(--bg-bg-overlay-l2)',
                              }}
                              aria-hidden
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
          <div className="detailActionBar-BhqrLr">
            <button className="detailBtn-j5pRnW" onClick={onClose} style={{
              background: 'transparent', border: '1px solid var(--border-border-neutral-l2)',
              borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer',
              display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
              height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
            }}>
              关闭
            </button>
            <button className="detailBtnPrimary-NtBx72" onClick={onContinueLearning} style={{
              background: 'var(--bg-bg-invert)', borderRadius: '4px',
              color: 'var(--text-text-onaccent)', cursor: 'pointer',
              display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
              height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
            }}>
              继续学习
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

function CreateGoalModal({ onClose, onCreate }: { onClose: () => void; onCreate: (title: string, description?: string) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()} style={{ width: '480px', height: 'auto' }}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailTitleGroup-cpT99c">
              <h2 className="detailTitle-X7zIZu">新建空间</h2>
              <p className="detailDescription-kBy0Ek">起个名字，Lumen 会在对话里帮你制定学习计划</p>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div style={{ padding: '20px', color: 'var(--text-text-secondary)', fontSize: '14px', lineHeight: '22px' }}>
            <label htmlFor="goal-name-input" style={{ display: 'block', marginBottom: '8px', color: 'var(--text-text-default)' }}>
              空间名称
            </label>
            <input
              id="goal-name-input"
              className="input-yEGQlg"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：掌握线性代数第三章"
              style={goalInputStyle}
            />
            <label htmlFor="goal-desc-input" style={{ display: 'block', marginTop: 16, marginBottom: '8px', color: 'var(--text-text-default)' }}>
              想学什么（可选）
            </label>
            <input
              id="goal-desc-input"
              className="input-yEGQlg"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="例如：围绕教材第三章，重点掌握行列式与特征值"
              style={goalInputStyle}
            />
            <p style={{ marginTop: 12, fontSize: 12 }}>
              创建后会打开一段引导学习，Lumen 会根据这个空间生成学习计划。
            </p>
          </div>
          <div className="detailActionBar-BhqrLr">
            <button className="detailBtn-j5pRnW" onClick={onClose} style={{
              background: 'transparent', border: '1px solid var(--border-border-neutral-l2)',
              borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer',
              display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
              height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
            }}>
              取消
            </button>
            <button
              className="detailBtnPrimary-NtBx72"
              disabled={!name.trim() || submitting}
              onClick={() => { setSubmitting(true); onCreate(name.trim(), description.trim() || undefined) }}
              style={{
                background: 'var(--bg-bg-invert)', borderRadius: '4px',
                color: 'var(--text-text-onaccent)', cursor: name.trim() && !submitting ? 'pointer' : 'not-allowed',
                display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
                height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
                opacity: name.trim() && !submitting ? 1 : 0.6,
              }}
            >
              {submitting ? '创建中…' : '创建空间'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

function RenameGoalModal({ goal, onClose, onRename }: { goal: LearningGoal; onClose: () => void; onRename: (title: string) => void }) {
  const [name, setName] = useState(goal.name || '')

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()} style={{ width: '480px', height: 'auto' }}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailTitleGroup-cpT99c">
              <h2 className="detailTitle-X7zIZu">重命名空间</h2>
              <p className="detailDescription-kBy0Ek">改名不会影响已记录的进度</p>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div style={{ padding: '20px' }}>
            <label htmlFor="goal-rename-input" style={{ display: 'block', marginBottom: '8px', color: 'var(--text-text-default)' }}>
              空间名称
            </label>
            <input
              id="goal-rename-input"
              className="input-yEGQlg"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={goalInputStyle}
            />
          </div>
          <div className="detailActionBar-BhqrLr">
            <button className="detailBtn-j5pRnW" onClick={onClose} style={{
              background: 'transparent', border: '1px solid var(--border-border-neutral-l2)',
              borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer',
              display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
              height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
            }}>
              取消
            </button>
            <button
              className="detailBtnPrimary-NtBx72"
              disabled={!name.trim()}
              onClick={() => { onRename(name.trim()); onClose() }}
              style={{
                background: 'var(--bg-bg-invert)', borderRadius: '4px',
                color: 'var(--text-text-onaccent)', cursor: name.trim() ? 'pointer' : 'not-allowed',
                display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
                height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
                opacity: name.trim() ? 1 : 0.6,
              }}
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

const goalInputStyle: React.CSSProperties = {
  width: '100%',
  background: 'var(--bg-bg-input)',
  border: '1px solid var(--border-border-neutral-l2)',
  borderRadius: '6px',
  color: 'var(--text-text-default)',
  fontSize: '14px',
  height: '32px',
  outline: 'none',
  padding: '0 10px',
}

/* ============ Marketplace Page (插件市场) ============ */
// 一级分类聚焦“插件能给 Lumen 带来什么能力”，而非消费型榜单。
const pluginCategories = ['推荐', '教学与学习', '资料处理', '搜索与研究', '工具与自动化', '集成']
// 辅助筛选：不展示评分/下载量等消费型指标。
const pluginFilters = ['全部', '官方', '已安装', '可更新']

type PluginState = 'installed' | 'available'

const plugins: PluginData[] = [
  { name: 'Socratic Tutor', description: '通过追问、提示和支架式教学帮助理解知识', publisher: 'Lumen', color: '🧑‍🏫', icon: '🧑‍🏫', category: '教学与学习', tags: ['对话式教学', '支架式'], version: '2.1.0', state: 'installed', official: true },
  { name: 'Flashcards', description: '从资料和知识点生成复习卡片', publisher: 'Lumen', color: '🃏', icon: '🃏', category: '教学与学习', tags: ['记忆', '复习'], version: '1.3.0', state: 'available', official: true },
  { name: 'Web Reader', description: '读取网页正文并转化为可学习资料', publisher: 'Lumen', color: '🌐', icon: '🌐', category: '资料处理', tags: ['网页', '提取正文'], version: '1.6.2', state: 'installed', official: true },
  { name: 'YouTube Importer', description: '导入视频字幕并生成学习材料', publisher: 'Lumen', color: '▶️', icon: '▶️', category: '资料处理', tags: ['视频', '字幕'], version: '1.0.4', state: 'available', official: false, canUpdate: true },
  { name: 'Deep Research', description: '围绕问题搜索、整理并综合多来源资料', publisher: 'Lumen', color: '🔎', icon: '🔎', category: '搜索与研究', tags: ['搜索', '综合'], version: '1.4.2', state: 'installed', official: true, canUpdate: true },
  { name: 'Zotero', description: '连接你的文献库，导出 BibTeX 并插入引文', publisher: 'Community', color: '📚', icon: '📚', category: '搜索与研究', tags: ['文献', '引用'], version: '1.1.0', state: 'available', official: false },
  { name: 'Notion Connector', description: '连接 Notion 并导入页面', publisher: 'Lumen', color: '🗒️', icon: '🗒️', category: '集成', tags: ['集成', '导入'], version: '1.2.0', state: 'available', official: true },
  { name: '飞书', description: '连接你的飞书账号，操作云文档、日历与消息', publisher: 'Lumen', color: '📱', icon: '📱', category: '集成', tags: ['集成'], version: '3.0.1', state: 'installed', official: true },
]

/* ============ Library Page (资料库) ============ */
// 资料库是真实知识库（Knowledge Base）的视图：每个已导入/已索引的资料 = 某个 KB raw/ 下的一个文件。
// 状态来自后端真实 pipeline（ready/processing/error），「导入资料」走 create/upload → 真实索引链。
type LibraryType = '文档' | '网页' | '图书' | '视频' | '音频' | '笔记'
type LibraryStatus = '已解析' | '处理中' | '解析失败'

interface LibraryItem {
  id: string
  name: string
  type: LibraryType
  kb: string
  path: string
  size: number
  addedAt: string
  status: LibraryStatus
  kbStatus: string
  kbError?: string
  icon: string
}

const libraryCategories = ['全部', '文档', '网页', '图书', '视频', '音频', '笔记']
const libraryFilters = ['全部状态', '已解析', '处理中', '解析失败']

function libraryTypeForPath(name: string): { type: LibraryType; icon: string } {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (['mp4', 'webm', 'mov', 'mkv'].includes(ext)) return { type: '视频', icon: '🎬' }
  if (['mp3', 'wav', 'm4a', 'aac', 'ogg'].includes(ext)) return { type: '音频', icon: '🎧' }
  if (['html', 'htm', 'mhtml'].includes(ext)) return { type: '网页', icon: '🌐' }
  if (['pdf'].includes(ext)) return { type: '图书', icon: '📖' }
  if (['md', 'markdown', 'txt', 'doc', 'docx', 'rtf'].includes(ext)) return { type: '文档', icon: '📄' }
  if (['ipynb', 'py', 'ts', 'tsx', 'js', 'jsx', 'cpp', 'c', 'java'].includes(ext)) return { type: '笔记', icon: '📝' }
  return { type: '文档', icon: '📄' }
}

function statusForKb(
  status: string | undefined,
  errorMsg?: string,
): { status: LibraryStatus; error?: string } {
  if (status === 'processing' || status === 'initializing') return { status: '处理中' }
  if (status === 'error') return { status: '解析失败', error: errorMsg }
  return { status: '已解析' }
}

function formatLibraryDate(ts?: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function formatFileSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

type SkillData = {
  name: string
  description: string
  publisher: string
  icon: string
  category?: string
}

export interface PluginData {
  name: string
  description: string
  publisher: string
  color: string
  icon: string
  category?: string
  tags?: string[]
  version?: string
  official?: boolean
  canUpdate?: boolean
  state?: PluginState
}

interface MarketplacePageProps {
  onSelectPlugin: (plugin: PluginData) => void
  sidebarBar?: React.ReactNode
}

export function MarketplacePage({ onSelectPlugin, sidebarBar }: MarketplacePageProps) {
  const [activeCategory, setActiveCategory] = useState('推荐')
  const [activeFilter, setActiveFilter] = useState('全部')
  const [searchText, setSearchText] = useState('')
  const [installedPlugins, setInstalledPlugins] = useState<Set<string>>(new Set(plugins.filter(p => p.state === 'installed').map(p => p.name)))

  const filteredPlugins = plugins.filter((p) => {
    const matchCategory = activeCategory === '推荐' || activeCategory === '全部' || p.category === activeCategory
    const hay = `${p.name} ${p.description} ${p.publisher} ${(p.tags ?? []).join(' ')}`.toLowerCase()
    const matchSearch = !searchText || hay.includes(searchText.toLowerCase())
    const matchFilter =
      activeFilter === '全部' ? true :
      activeFilter === '官方' ? !!p.official :
      activeFilter === '已安装' ? installedPlugins.has(p.name) :
      activeFilter === '可更新' ? installedPlugins.has(p.name) && !!p.canUpdate : true
    return matchCategory && matchSearch && matchFilter
  })

  const toggleInstall = (name: string) => {
    setInstalledPlugins(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  // “推荐”作为精选首屏，未选中具体分类时按能力分类分组展示。
  const shown = activeCategory === '推荐'
    ? pluginCategories
        .filter((c) => c !== '推荐')
        .map((cat) => ({ title: cat, plugins: filteredPlugins.filter((p) => p.category === cat) }))
        .filter((g) => g.plugins.length > 0)
    : [{ title: activeCategory, plugins: filteredPlugins }]

  return (
    <>
      {sidebarBar && (
        <header className="header-x7rPuS">
          <div className="headerLeft-rH3lhm">{sidebarBar}</div>
          <div className="headerCenter-cba9zB" />
          <div className="headerRight-QHfr9M" />
        </header>
      )}
      <div className="marketplacePage-U60AB4">
        <div className="root-Bkr7v6">
          <div className="scrollArea-fvGujy">
            <div className="scrollContent-Q7fN_Z">
              <div className="headerRail-GfhRry">
                <div className="titleGroup-R6DD_m">
                  <h1 className="title-yQrHui">插件市场</h1>
                  <p className="subtitle-Gi_Tjb">为 {PRODUCT_NAME} 扩展新的学习、研究与知识处理能力</p>
                </div>
              </div>
              <div className="stickyNavigation-vpcdcv">
                <div className="toolbarRail-Qlt0C7">
                  <div className="toolbarEnd-CGhDms">
                    <div className="searchSlot-ionH2H">
                      <div className="searchInputInputRoot-ql5R96">
                        <span className="searchInputInputIcon-_qGz4O">
                          <PageIcon name="search" size={16} />
                        </span>
                        <input
                          className="input-yEGQlg"
                          placeholder="搜索插件、能力或开发者"
                          name="marketplace-search"
                          aria-label="搜索插件、能力或开发者"
                          value={searchText}
                          onChange={(e) => setSearchText(e.target.value)}
                          style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-text-default)', fontSize: '13px' }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
                <div className="filtersRail-_VFXr1">
                  <div className="categoryNav-TtjHNd">
                    {pluginCategories.map((cat) => (
                      <button
                        key={cat}
                        type="button"
                        className={activeCategory === cat ? 'categoryNavItemActive-k6zapU' : 'categoryNavItem-HXakRf'}
                        onClick={() => setActiveCategory(cat)}
                      >
                        {cat}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="filtersRail-_VFXr1" style={{ paddingTop: 0 }}>
                  <div className="categoryNav-TtjHNd">
                    {pluginFilters.map((f) => (
                      <button
                        key={f}
                        type="button"
                        className={activeFilter === f ? 'categoryNavItemActive-k6zapU' : 'categoryNavItem-HXakRf'}
                        onClick={() => setActiveFilter(f)}
                      >
                        {f}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="contentRail-dRMjXS">
                <div className="pluginsContentInner-amtMMJ">
                  {shown.length === 0 ? (
                    <div style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '20px', padding: '24px 0' }}>没有找到匹配的插件。</div>
                  ) : shown.map((section) => (
                    <div key={section.title} className="categorySection-T0Z3c3">
                      <span className="categorySectionTitle-b_hOUf">{section.title}</span>
                      <div className="pluginsGrid-u71c96">
                        {section.plugins.map((p) => {
                          const isInstalled = installedPlugins.has(p.name)
                          const label = !isInstalled ? '安装' : (p.canUpdate ? '更新' : '打开')
                          const actionStyle: React.CSSProperties = isInstalled
                            ? { alignItems: 'center', background: 'transparent', border: '1px solid var(--border-border-neutral-l2)', borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer', display: 'inline-flex', fontSize: '12px', gap: '4px', height: '28px', justifyContent: 'center', lineHeight: '16px', padding: '0 10px' }
                            : { alignItems: 'center', background: 'var(--bg-bg-invert)', border: 'none', borderRadius: '4px', color: 'var(--text-text-onaccent)', cursor: 'pointer', display: 'inline-flex', fontSize: '12px', gap: '4px', height: '28px', justifyContent: 'center', lineHeight: '16px', padding: '0 10px' }
                          return (
                            <div key={p.name} className="pluginCard-cq4jH5" onClick={() => onSelectPlugin(p)}>
                              <div className="pluginCardHeader-RvwB47">
                                <div className="marketIcon-ZTaS8Y">
                                  <span className="marketIconPluginImage-hG9jDA">{p.icon}</span>
                                </div>
                                <div className="pluginCardBody-bY5she">
                                  <span className="pluginCardName-ncj_7T">{p.name}</span>
                                  <span className="pluginCardDesc-bK19VV">{p.description}</span>
                                </div>
                                <button
                                  type="button"
                                  style={actionStyle}
                                  onClick={(e) => { e.stopPropagation(); toggleInstall(p.name) }}
                                >
                                  {label}
                                </button>
                              </div>
                              <div style={{ alignItems: 'center', display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '12px', minWidth: 0 }}>
                                <span style={{ color: 'var(--text-text-secondary)', fontSize: '12px', lineHeight: '18px' }}>{p.publisher}</span>
                                {p.version && <span style={{ color: 'var(--text-text-tertiary)', fontSize: '12px', lineHeight: '18px' }}>v{p.version}</span>}
                                {p.official && (
                                  <span style={{ background: 'var(--bg-bg-overlay-l1)', borderRadius: '4px', color: 'var(--text-text-secondary)', fontSize: '11px', lineHeight: '16px', padding: '1px 6px' }}>官方</span>
                                )}
                              </div>
                              {(p.tags ?? []).length > 0 && (
                                <div style={{ alignItems: 'center', display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
                                  {(p.tags ?? []).map((t) => (
                                    <span key={t} style={{ border: '1px solid var(--border-border-neutral-l1)', borderRadius: '4px', color: 'var(--text-text-secondary)', fontSize: '11px', lineHeight: '16px', padding: '1px 6px' }}>{t}</span>
                                  ))}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

/* ============ Library Page (资料库) ============ */
interface LibraryPageProps {
  sidebarBar?: React.ReactNode
}

const libraryStatusColor: Record<LibraryStatus, string> = {
  '已解析': 'rgba(70,180,120,0.14)',
  '处理中': 'rgba(230,168,64,0.16)',
  '解析失败': 'rgba(224,80,80,0.14)',
}

const libraryItemBtn: React.CSSProperties = {
  alignItems: 'center',
  borderRadius: '4px',
  cursor: 'pointer',
  display: 'inline-flex',
  fontSize: '12px',
  gap: '4px',
  height: '28px',
  justifyContent: 'center',
  lineHeight: '16px',
}

export function LibraryPage({ sidebarBar }: LibraryPageProps) {
  const [activeCategory, setActiveCategory] = useState('全部')
  const [activeFilter, setActiveFilter] = useState('全部状态')
  const [searchText, setSearchText] = useState('')
  const [items, setItems] = useState<LibraryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [importFiles, setImportFiles] = useState<File[] | null>(null)
  const [preview, setPreview] = useState<LibraryItem | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<LibraryItem | null>(null)
  const [busyAdding, setBusyAdding] = useState<Set<string>>(new Set())
  const [added, setAdded] = useState<Set<string>>(new Set())
  const [toast, setToast] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadLibrary = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const kbs = await listKnowledgeBases()
      const entries = await Promise.all(
        kbs.map(async (kb) => {
          const files = await listKbFiles(kb.name).catch(() => [] as KbFile[])
          const st = statusForKb(kb.status, kb.progress?.error || kb.metadata?.last_error)
          return files
            .filter((f) => f.type === 'file')
            .map((f) => {
              const { type, icon } = libraryTypeForPath(f.name)
              return {
                id: `${kb.name}::${f.name}`,
                name: f.name,
                type,
                icon,
                kb: kb.name,
                path: f.name,
                size: f.size ?? 0,
                addedAt: formatLibraryDate(f.modified),
                status: st.status,
                kbStatus: kb.status ?? 'unknown',
                kbError: st.error,
              } as LibraryItem
            })
        }),
      )
      setItems(entries.flat())
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '加载资料库失败，请确认后端服务已启动')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // Deferred so loadLibrary's setState runs in a callback, not
    // synchronously inside the effect (react-hooks/set-state-in-effect).
    const id = window.setTimeout(loadLibrary, 0)
    return () => window.clearTimeout(id)
  }, [loadLibrary])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(t)
  }, [toast])

  const onImportComplete = useCallback(() => {
    setImportFiles(null)
    loadLibrary()
  }, [loadLibrary])

  const onRetry = useCallback(async (it: LibraryItem) => {
    setToast(null)
    try {
      await retryKb(it.kb)
      setToast({ kind: 'success', text: `已重新排队解析「${it.name}」所在的资料库` })
      loadLibrary()
      const poll = window.setInterval(async () => {
        try {
          const info = await getKbInfo(it.kb)
          if (info.status === 'ready' || info.status === 'error') {
            window.clearInterval(poll)
            loadLibrary()
          }
        } catch {
          /* transient poll errors ignored */
        }
      }, 3000)
    } catch (e) {
      setToast({ kind: 'error', text: e instanceof Error ? e.message : '重新解析失败' })
    }
  }, [loadLibrary])

  const onAddToSpace = useCallback(async (it: LibraryItem) => {
    setBusyAdding((cur) => new Set(cur).add(it.id))
    setToast(null)
    try {
      await createLearningGoal(it.name, `围绕「${it.name}」制定学习计划`, it.kb)
      setAdded((cur) => new Set(cur).add(it.id))
      setToast({ kind: 'success', text: `「${it.name}」已加入学习空间` })
    } catch (e) {
      setToast({ kind: 'error', text: e instanceof Error ? e.message : '添加到学习空间失败' })
    } finally {
      setBusyAdding((cur) => {
        const next = new Set(cur)
        next.delete(it.id)
        return next
      })
    }
  }, [])

  const onDelete = useCallback(async (it: LibraryItem) => {
    setConfirmDelete(null)
    setToast(null)
    try {
      await deleteKbFile(it.kb, it.path)
      setItems((cur) => cur.filter((x) => x.id !== it.id))
      setToast({ kind: 'success', text: `已删除「${it.name}」` })
    } catch (e) {
      setToast({ kind: 'error', text: e instanceof Error ? e.message : '删除失败' })
    }
  }, [])

  const shownItems = items.filter((it) => {
    const matchCategory = activeCategory === '全部' || it.type === activeCategory
    const hay = `${it.name} ${it.type} ${it.kb}`.toLowerCase()
    const matchSearch = !searchText || hay.includes(searchText.toLowerCase())
    const matchFilter = activeFilter === '全部状态' || it.status === activeFilter
    return matchCategory && matchSearch && matchFilter
  })

  return (
    <>
      {sidebarBar && (
        <header className="header-x7rPuS">
          <div className="headerLeft-rH3lhm">{sidebarBar}</div>
          <div className="headerCenter-cba9zB" />
          <div className="headerRight-QHfr9M" />
        </header>
      )}
      <div className="marketplacePage-U60AB4">
        <div className="root-Bkr7v6">
          <div className="scrollArea-fvGujy">
            <div className="scrollContent-Q7fN_Z">
              <div className="headerRail-GfhRry">
                <div className="titleGroup-R6DD_m">
                  <h1 className="title-yQrHui">资料库</h1>
                  <p className="subtitle-Gi_Tjb">管理你在 {PRODUCT_NAME} 中导入的资料；导入后自动解析并建立索引，可供知识检索使用</p>
                </div>
                <div className="headerActions-TKXare" style={{ display: 'flex', gap: '8px' }}>
                  <button
                    type="button"
                    className="button-muTeiY secondary-J0eGRO large-psSWuL"
                    style={{
                      ...headerBtnBase,
                      background: 'transparent',
                      border: '1px solid var(--border-border-neutral-l2)',
                      color: 'var(--text-text-default)',
                    }}
                    onClick={loadLibrary}
                  >
                    <span>刷新</span>
                  </button>
                  <button
                    type="button"
                    className="button-muTeiY primary-ZG2S1H large-psSWuL"
                    style={{
                      ...headerBtnBase,
                      background: 'var(--bg-bg-invert)',
                      border: 'none',
                      color: 'var(--text-text-onaccent)',
                    }}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <PageIcon name="download" size={14} />
                    <span>导入资料</span>
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    hidden
                    accept=".md,.markdown,.txt,.pdf,.doc,.docx,.rtf,.html,.htm,.mp3,.wav,.m4a,.mp4,.webm,.zip"
                    onChange={(e) => {
                      const files = Array.from(e.target.files ?? [])
                      if (files.length > 0) setImportFiles(files)
                      e.target.value = ''
                    }}
                  />
                </div>
              </div>
              <div className="stickyNavigation-vpcdcv">
                <div className="toolbarRail-Qlt0C7">
                  <div className="toolbarEnd-CGhDms">
                    <div className="searchSlot-ionH2H">
                      <div className="searchInputInputRoot-ql5R96">
                        <span className="searchInputInputIcon-_qGz4O">
                          <PageIcon name="search" size={16} />
                        </span>
                        <input
                          className="input-yEGQlg"
                          placeholder="搜索资料、类型或所属知识库"
                          name="library-search"
                          aria-label="搜索资料、类型或所属知识库"
                          value={searchText}
                          onChange={(e) => setSearchText(e.target.value)}
                          style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-text-default)', fontSize: '13px' }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
                <div className="filtersRail-_VFXr1">
                  <div className="categoryNav-TtjHNd">
                    {libraryCategories.map((cat) => (
                      <button
                        key={cat}
                        type="button"
                        className={activeCategory === cat ? 'categoryNavItemActive-k6zapU' : 'categoryNavItem-HXakRf'}
                        onClick={() => setActiveCategory(cat)}
                      >
                        {cat}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="filtersRail-_VFXr1" style={{ paddingTop: 0 }}>
                  <div className="categoryNav-TtjHNd">
                    {libraryFilters.map((f) => (
                      <button
                        key={f}
                        type="button"
                        className={activeFilter === f ? 'categoryNavItemActive-k6zapU' : 'categoryNavItem-HXakRf'}
                        onClick={() => setActiveFilter(f)}
                      >
                        {f}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="contentRail-dRMjXS">
                <div className="pluginsContentInner-amtMMJ">
                  {loading ? (
                    <div style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '20px', padding: '24px 0' }}>正在加载资料库…</div>
                  ) : loadError ? (
                    <div
                      style={{
                        border: '1px solid var(--status-error-default, #f65a5a)',
                        borderRadius: 8,
                        padding: '12px 16px',
                        color: 'var(--status-error-default, #f65a5a)',
                        fontSize: 13,
                      }}
                    >
                      {loadError}
                      <button
                        type="button"
                        onClick={loadLibrary}
                        style={{ background: 'transparent', border: 'none', color: 'var(--text-text-link)', cursor: 'pointer', fontSize: 13, marginLeft: 12 }}
                      >
                        重试
                      </button>
                    </div>
                  ) : shownItems.length === 0 ? (
                    <div style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '20px', padding: '24px 0' }}>
                      这里空空如也，点击右上角「导入资料」上传文档，{PRODUCT_NAME} 会自动解析并建立索引。
                    </div>
                  ) : (
                    <div className="pluginsGrid-u71c96">
                      {shownItems.map((it) => {
                        const addedNow = added.has(it.id)
                        const adding = busyAdding.has(it.id)
                        return (
                          <div key={it.id} className="pluginCard-cq4jH5">
                            <div className="pluginCardHeader-RvwB47">
                              <div className="marketIcon-ZTaS8Y">
                                <span className="marketIconPluginImage-hG9jDA">{it.icon}</span>
                              </div>
                              <div className="pluginCardBody-bY5she">
                                <span className="pluginCardName-ncj_7T">{it.name}</span>
                                <span className="pluginCardDesc-bK19VV">{it.type}{it.size > 0 ? ` · ${formatFileSize(it.size)}` : ''}</span>
                              </div>
                              <span
                                title={it.kbError}
                                style={{ background: libraryStatusColor[it.status], borderRadius: '4px', color: 'var(--text-text-secondary)', flexShrink: 0, fontSize: '11px', lineHeight: '16px', padding: '2px 8px' }}
                              >
                                {it.status}
                              </span>
                            </div>
                            <div style={{ color: 'var(--text-text-tertiary)', display: 'flex', flexWrap: 'wrap', fontSize: '12px', gap: '4px', lineHeight: '18px', marginTop: '12px' }}>
                              <span>{it.kb}</span>
                              <span>· 加入于 {it.addedAt}</span>
                            </div>
                            {it.status === '解析失败' && it.kbError && (
                              <div style={{ color: 'var(--status-error-default, #f65a5a)', fontSize: '11px', lineHeight: '16px', marginTop: '6px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={it.kbError}>
                                {it.kbError}
                              </div>
                            )}
                            <div style={{ alignItems: 'center', display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '14px' }}>
                              <button
                                type="button"
                                onClick={() => setPreview(it)}
                                style={{ ...libraryItemBtn, background: 'var(--bg-bg-invert)', border: 'none', color: 'var(--text-text-onaccent)', padding: '0 12px' }}
                              >
                                打开
                              </button>
                              <button
                                type="button"
                                disabled={adding}
                                onClick={() => onAddToSpace(it)}
                                style={{ ...libraryItemBtn, background: 'transparent', border: '1px solid var(--border-border-neutral-l2)', color: 'var(--text-text-default)', padding: '0 10px', opacity: adding ? 0.6 : 1 }}
                              >
                                {adding ? '添加中…' : (addedNow ? '已加入学习空间' : '添加到学习空间')}
                              </button>
                              {it.status === '解析失败' && (
                                <button
                                  type="button"
                                  onClick={() => onRetry(it)}
                                  style={{ ...libraryItemBtn, background: 'transparent', border: '1px solid var(--border-border-neutral-l2)', color: 'var(--text-text-default)', padding: '0 10px' }}
                                >
                                  重新解析
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => setConfirmDelete(it)}
                                style={{ ...libraryItemBtn, background: 'transparent', border: 'none', color: 'var(--text-text-tertiary)', marginLeft: 'auto', padding: '0 8px' }}
                              >
                                删除
                              </button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      {toast && (
        <div
          className="libraryToast"
          style={{
            position: 'fixed',
            bottom: 24,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 100,
            background: toast.kind === 'error' ? 'var(--status-error-default, #f65a5a)' : 'var(--bg-bg-invert)',
            color: toast.kind === 'error' ? '#fff' : 'var(--text-text-onaccent)',
            borderRadius: 6,
            boxShadow: '0 6px 24px rgba(0,0,0,0.28)',
            fontSize: 13,
            lineHeight: '20px',
            maxWidth: 480,
            padding: '8px 16px',
          }}
        >
          {toast.text}
        </div>
      )}
      {importFiles && (
        <ImportMaterialsModal files={importFiles} onClose={() => setImportFiles(null)} onComplete={onImportComplete} />
      )}
      {preview && <MaterialPreviewModal item={preview} onClose={() => setPreview(null)} />}
      {confirmDelete && (
        <ConfirmDeleteModal item={confirmDelete} onCancel={() => setConfirmDelete(null)} onConfirm={() => onDelete(confirmDelete)} />
      )}
    </>
  )
}

/* ============ 导入资料 Modal ============ */
type ImportPhase = 'confirm' | 'submitting' | 'processing' | 'done' | 'error'

interface ImportMaterialsModalProps {
  files: File[]
  onClose: () => void
  onComplete: () => void
}

function ImportMaterialsModal({ files, onClose, onComplete }: ImportMaterialsModalProps) {
  const [phase, setPhase] = useState<ImportPhase>('confirm')
  const [targetExists, setTargetExists] = useState(false)
  const [progress, setProgress] = useState<{ percent: number; message: string } | null>(null)
  const [error, setError] = useState('')
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false
    listKnowledgeBases()
      .then((kbs) => { if (!cancelled) setTargetExists(kbs.some((k) => k.name === LIBRARY_KB_NAME)) })
      .catch(() => { if (!cancelled) setTargetExists(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    }
  }, [onClose])

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const startPolling = () => {
    stopPolling()
    let elapsed = 0
    pollRef.current = window.setInterval(async () => {
      elapsed += 2500
      try {
        const info = await getKbInfo(LIBRARY_KB_NAME)
        if (info.status === 'ready') {
          stopPolling()
          setProgress(null)
          setPhase('done')
          return
        }
        if (info.status === 'error') {
          stopPolling()
          setError(info.progress?.error || info.metadata?.last_error || '资料解析失败')
          setPhase('error')
          return
        }
        const p = info.progress
        if (p && typeof p.percent === 'number') {
          setProgress({ percent: p.percent, message: p.message || '' })
        } else {
          setProgress((cur) => cur ?? { percent: 0, message: '正在解析并建立索引…' })
        }
      } catch {
        /* transient poll errors ignored */
      }
      if (elapsed > 10 * 60 * 1000) {
        stopPolling()
        setError('处理超时，请稍后在资料库中查看状态')
        setPhase('error')
      }
    }, 2500)
  }

  const submit = async () => {
    setPhase('submitting')
    setError('')
    try {
      if (targetExists) {
        await uploadFilesToKb(LIBRARY_KB_NAME, files)
      } else {
        await createKnowledgeBase(LIBRARY_KB_NAME, files)
      }
      setPhase('processing')
      setProgress({ percent: 0, message: targetExists ? '已上传，正在解析并建立索引…' : '正在创建资料库并建立索引…' })
      startPolling()
    } catch (e) {
      setError(e instanceof Error ? e.message : '导入失败，请稍后重试')
      setPhase('error')
    }
  }

  const busy = phase === 'submitting' || phase === 'processing'

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={() => { if (!busy) onClose() }}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()} style={{ width: '520px', height: 'auto' }}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailTitleGroup-cpT99c">
              <h2 className="detailTitle-X7zIZu">导入资料</h2>
              <p className="detailDescription-kBy0Ek">上传的资料会进入「{LIBRARY_KB_NAME}」知识库，自动解析并建立索引</p>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} disabled={busy} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: busy ? 'default' : 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', opacity: busy ? 0.5 : 1, width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div style={{ padding: '4px 20px 20px', color: 'var(--text-text-secondary)', fontSize: 14, lineHeight: '22px' }}>
            {phase === 'confirm' && (
              <>
                <div style={{ maxHeight: 200, overflow: 'auto', border: '1px solid var(--border-border-neutral-l2)', borderRadius: 8, padding: '4px 12px' }}>
                  {files.map((f) => (
                    <div key={f.name} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 0', fontSize: 13 }}>
                      <span style={{ color: 'var(--text-text-default)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                      <span style={{ flexShrink: 0 }}>{formatFileSize(f.size)}</span>
                    </div>
                  ))}
                </div>
                <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-text-tertiary)' }}>
                  {targetExists
                    ? `目标知识库「${LIBRARY_KB_NAME}」已存在，将增量导入并重建索引。`
                    : `首次导入会自动创建知识库「${LIBRARY_KB_NAME}」。`}
                  支持 md / pdf / txt / doc / docx / html 等常见文档格式。
                </p>
              </>
            )}
            {phase === 'submitting' && <p>正在上传文件…</p>}
            {phase === 'processing' && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
                  <span style={{ color: 'var(--text-text-default)' }}>{progress?.message || '正在处理…'}</span>
                  <span>{progress ? Math.round(progress.percent) : 0}%</span>
                </div>
                <div className="goalProgressTrack" style={{ position: 'relative', display: 'inline-block', width: '100%', height: 8, borderRadius: 4, background: 'var(--bg-bg-overlay-l1)' }}>
                  <span
                    className="goalProgressFill"
                    style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${progress ? Math.round(progress.percent) : 0}%`, borderRadius: 4, background: 'var(--bg-bg-invert)' }}
                    aria-hidden
                  />
                </div>
                <p style={{ marginTop: 10, fontSize: 12, color: 'var(--text-text-tertiary)' }}>
                  关闭窗口不会取消任务：资料仍会在后台解析，完成后自动出现在资料库。
                </p>
              </div>
            )}
            {phase === 'done' && (
              <div style={{ border: '1px solid var(--border-border-neutral-l2)', borderRadius: 8, padding: '12px 16px' }}>
                <p style={{ color: 'var(--text-text-default)', fontSize: 14, fontWeight: 500, marginBottom: 4 }}>导入完成</p>
                <p style={{ fontSize: 13 }}>{files.length} 个文件已成功解析并建立索引，可在资料库中打开，也可在对话中通过知识检索使用。</p>
              </div>
            )}
            {phase === 'error' && (
              <div style={{ border: '1px solid var(--status-error-default, #f65a5a)', borderRadius: 8, padding: '12px 16px' }}>
                <p style={{ color: 'var(--status-error-default, #f65a5a)', fontSize: 13 }}>导入失败</p>
                <p style={{ fontSize: 12, marginTop: 4, wordBreak: 'break-all' }}>{error}</p>
              </div>
            )}
          </div>
          <div className="detailActionBar-BhqrLr">
            {phase === 'confirm' && (
              <>
                <button className="detailBtn-j5pRnW" onClick={onClose} style={{ background: 'transparent', border: '1px solid var(--border-border-neutral-l2)', borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
                  取消
                </button>
                <button className="detailBtnPrimary-NtBx72" onClick={submit} style={{ background: 'var(--bg-bg-invert)', borderRadius: '4px', color: 'var(--text-text-onaccent)', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
                  开始导入
                </button>
              </>
            )}
            {phase === 'submitting' && <p style={{ fontSize: 13, marginLeft: 'auto' }}>上传中…</p>}
            {phase === 'processing' && (
              <button className="detailBtn-j5pRnW" onClick={onClose} style={{ background: 'transparent', border: '1px solid var(--border-border-neutral-l2)', borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
                后台处理
              </button>
            )}
            {phase === 'done' && (
              <button className="detailBtnPrimary-NtBx72" onClick={onComplete} style={{ background: 'var(--bg-bg-invert)', borderRadius: '4px', color: 'var(--text-text-onaccent)', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
                完成
              </button>
            )}
            {phase === 'error' && (
              <>
                <button className="detailBtn-j5pRnW" onClick={onClose} style={{ background: 'transparent', border: '1px solid var(--border-border-neutral-l2)', borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
                  关闭
                </button>
                <button className="detailBtnPrimary-NtBx72" onClick={submit} style={{ background: 'var(--bg-bg-invert)', borderRadius: '4px', color: 'var(--text-text-onaccent)', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
                  重试
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

/* ============ 资料预览 Modal ============ */
interface MaterialPreviewModalProps {
  item: LibraryItem
  onClose: () => void
}

function MaterialPreviewModal({ item, onClose }: MaterialPreviewModalProps) {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    // 初始 loading/error 即为目标值，异步回调里才 setState（避免 set-state-in-effect）
    fetchKbFilePreview(item.kb, item.path)
      .then((t) => { if (!cancelled) setText(t) })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : '预览失败') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [item.kb, item.path])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()} style={{ width: '640px', height: 'auto', maxHeight: '80vh' }}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailTitleGroup-cpT99c">
              <h2 className="detailTitle-X7zIZu">{item.name}</h2>
              <p className="detailDescription-kBy0Ek">{item.kb} · {item.type}</p>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div style={{ padding: '4px 20px 20px', color: 'var(--text-text-secondary)', fontSize: 13, lineHeight: '22px' }}>
            {loading && <p>正在加载内容…</p>}
            {error && <p style={{ color: 'var(--status-error-default, #f65a5a)' }}>{error}</p>}
            {!loading && !error && (
              <pre style={{ background: 'var(--bg-bg-overlay-l1)', borderRadius: 8, padding: 16, fontSize: 13, lineHeight: '22px', color: 'var(--text-text-default)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '52vh', overflow: 'auto', margin: 0 }}>{text}</pre>
            )}
          </div>
          <div className="detailActionBar-BhqrLr">
            <button className="detailBtn-j5pRnW" onClick={onClose} style={{ background: 'transparent', border: '1px solid var(--border-border-neutral-l2)', borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
              关闭
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

/* ============ 删除确认 Modal ============ */
interface ConfirmDeleteModalProps {
  item: LibraryItem
  onCancel: () => void
  onConfirm: () => void
}

function ConfirmDeleteModal({ item, onCancel, onConfirm }: ConfirmDeleteModalProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onCancel])

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onCancel}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()} style={{ width: '440px', height: 'auto' }}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailTitleGroup-cpT99c">
              <h2 className="detailTitle-X7zIZu">删除资料</h2>
              <p className="detailDescription-kBy0Ek">此操作会移除该文件及其索引记录</p>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onCancel} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div style={{ padding: '20px', fontSize: 13, color: 'var(--text-text-secondary)', lineHeight: '22px' }}>
            确定删除「<b style={{ color: 'var(--text-text-default)' }}>{item.name}</b>」吗？
            删除后该文件将从资料库移除，若已被索引，下一次重新索引时会被清除。
          </div>
          <div className="detailActionBar-BhqrLr">
            <button className="detailBtn-j5pRnW" onClick={onCancel} style={{ background: 'transparent', border: '1px solid var(--border-border-neutral-l2)', borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
              取消
            </button>
            <button className="detailBtnPrimary-NtBx72" onClick={onConfirm} style={{ background: 'var(--status-error-default, #f65a5a)', borderRadius: '4px', color: '#fff', cursor: 'pointer', display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px', height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px' }}>
              删除
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

/* ============ Workspace Page (main chat view) ============ */
export function WorkspacePage() {
  return (
    <div className="workspacePage" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="header-fId8VF">
        <div className="headerCenter-HRprYa">
          <div className="taskHeader-wmHGD9">
            <span className="wrapper-RV5xqM">
              <div className="infoArea-Y4r_8m">
                <div className="iconWrap-_fRuU8">
                  <PageIcon name="spaces" size={14} />
                </div>
                <span className="taskName-iaeIsX">Greeting</span>
                <div className="timeWrap-ksZO3X">
                  <span className="timeText-bjF8AM">18:12</span>
                </div>
              </div>
            </span>
            <div className="moreBtn-h2uOKe">
              <PageIcon name="down" size={16} />
            </div>
          </div>
        </div>
      </div>
      <div className="workspace-nQt_sr">
        <div className="mainContent-I6jtPZ">
          <div id="agent-chat-view" className="chatArea-zQPQwl">
            <div className="chatInner-c6091C">
              <div className="chatContent-h48jjm">
                <div className="ai-chat chat-session">
                  <div className="virtualized-message-list-view">
                    <div className="virtualized-message-list-view__content">
                      <div className="virtualized-message-list-view__scroller virtualized-message-list-view__scroller--hide-scrollbar">
                        <div className="virtualized-message-list-view__virtuoso" style={{ position: 'relative' }}>
                          <div className="turn turn--last" data-turn-id="m-2">
                            <div className="turn__agent-row">
                              <div className="turn__agent-message" data-role="assistant">
                                <div data-item-type="turn:assistant-avatar">
                                  <div className="agent-message__header">
                                    <div className="agent-avatar agent-avatar--solo-code" style={{ width: 18, height: 18 }}>
                                      <PageIcon name="code" size={12} />
                                    </div>
                                    <span className="agent-message__title">Lumen</span>
                                  </div>
                                </div>
                                <div className="markdown-renderer">
                                  <p className="markdown-p">你好！我是 Lumen，有什么可以帮你的？</p>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ============ Skill Detail Modal ============ */
interface SkillDetailProps {
  skill: SkillData
  onClose: () => void
}

export function SkillDetailModal({ skill, onClose }: SkillDetailProps) {
  const [installing, setInstalling] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const alipayMarkdown = (
    <div className="detailMarkdownInner-grR20b">
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 16px 0' }}>
        所有支付宝支付产品的文档均为在线动态链接，接入前务必阅读对应产品的在线文档获取最新接口参数和代码示例。
      </p>
      <h2 style={{ color: 'var(--text-text-default)', fontSize: '16px', fontWeight: 600, margin: '0 0 12px 0' }}>
        文档访问规范
      </h2>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 12px 0' }}>
        访问支付宝在线文档时，直接使用 curl 获取内容：
      </p>
      <pre style={{ background: 'var(--bg-bg-overlay-l1)', borderRadius: '6px', padding: '12px', fontSize: '12px', color: 'var(--text-text-secondary)', overflow: 'auto', margin: '0 0 16px 0' }}>
{`# 示例: 获取当面付文档
curl -sL "https://ideservice.alipay.com/cms/site/0izcu3"`}
      </pre>
      <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 12px 0' }}>
        递归访问
      </h3>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 12px 0' }}>
        文档页面可能包含子链接，你必须自动跟进所有子链接以获取完整文档。具体规则：
      </p>
      <ol style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 16px 20px', padding: 0 }}>
        <li>仅跟进文档正文中的 URL</li>
        <li>忽略站内导航链接（产品首页、产品列表、产品分类、产品索引等）</li>
        <li>除非文档明确要求，否则跳过认证步骤</li>
      </ol>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 12px 0' }}>
        递归访问文档页面：
      </p>
      <pre style={{ background: 'var(--bg-bg-overlay-l1)', borderRadius: '6px', padding: '12px', fontSize: '12px', color: 'var(--text-text-secondary)', overflow: 'auto', margin: '0 0 16px 0' }}>
{`# 访问除最后一页外的所有页面
curl -sL "https://ideservice.alipay.com/cms/site/0izal0"   # 支付渠道
curl -sL "https://ideservice.alipay.com/cms/site/0izal1"   # 营销促销`}
      </pre>
      <h2 style={{ color: 'var(--text-text-default)', fontSize: '16px', fontWeight: 600, margin: '0 0 12px 0' }}>
        密钥配置方式
      </h2>
      <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 8px 0' }}>
        步骤1. 密钥获取方式
      </h3>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 12px 0' }}>
        登录支付宝开放平台获取应用的 AppID、支付宝公钥以及应用私钥。应用公钥不需要手动配置，使用 RSA2 即可。
      </p>
      <ul style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 16px 20px', padding: 0 }}>
        <li><strong style={{ color: 'var(--text-text-default)' }}>创建应用</strong>：在支付宝开放平台创建应用，获取 AppID。<a style={{ color: 'var(--text-text-link)' }} href="#">了解更多</a></li>
        <li><strong style={{ color: 'var(--text-text-default)' }}>配置密钥</strong>：使用 RSA2 生成密钥对，配置应用公钥。<a style={{ color: 'var(--text-text-link)' }} href="#">配置方法</a></li>
      </ul>
      <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 8px 0' }}>
        步骤2. 配置应用密钥
      </h3>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: 0 }}>
        在配置文件中设置应用的 AppID、应用私钥、支付宝公钥等参数。务必使用配置文件管理密钥，不要将密钥硬编码在代码或提交到代码仓库中。
      </p>
    </div>
  )

  const isAlipay = skill.name === 'alipay-payment-integration'

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailHeaderRow-L8ZCMj">
              <div className="detailIcon-qGQGfs">
                <span style={{ fontSize: '24px' }}>{skill.icon}</span>
              </div>
              <div className="detailTitleGroup-cpT99c">
                <h2 className="detailTitle-X7zIZu">{skill.name}</h2>
                <p className="detailPublisher-VPxyqw">by {skill.publisher}</p>
              </div>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div className="detailDocSection-Mil5SR">
            <div className="detailDescriptionCard-FtwEk8">
              <p className="detailDescriptionText-apMOdF">
                {skill.description}
              </p>
            </div>
            <div className="detailMarkdownCard-kxmm37">
              {isAlipay ? alipayMarkdown : (
                <div className="detailMarkdownInner-grR20b">
                  <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 8px 0' }}>
                    技能说明
                  </h3>
                  <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: 0 }}>
                    {skill.description}
                  </p>
                </div>
              )}
            </div>
          </div>
          <div className="detailActionBar-BhqrLr">
            <div className="detailActionRight-CxGqmX" style={{ marginLeft: 'auto' }}>
              <button
                className="detailBtnPrimary-NtBx72"
                disabled={installing}
                onClick={() => setInstalling(true)}
                style={{
                  background: 'var(--bg-bg-invert)', borderRadius: '4px',
                  color: 'var(--text-text-onaccent)', cursor: installing ? 'not-allowed' : 'pointer',
                  display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
                  height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
                  opacity: installing ? 0.6 : 1,
                }}
              >
                {installing ? '安装中...' : '+ 安装技能'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

/* ============ Plugin Detail Modal ============ */
interface PluginDetailProps {
  plugin: PluginData
  onClose: () => void
}

const skillTemplates = [
  { name: 'alipay-payment-integration', desc: '支付宝支付产品接入最佳实践指南，涵盖从线下到线上的全场景支付。', icon: '💰' },
  { name: 'byted-bp-cdn-pagesdeploy', desc: '一键部署静态网站至 BytePlus Edge Pages 平台。', icon: '🚀' },
]

export function PluginDetailModal({ plugin, onClose }: PluginDetailProps) {
  const [installing, setInstalling] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailHeaderRow-L8ZCMj">
              <div className="detailIcon-qGQGfs">
                <span style={{ fontSize: '24px' }}>{plugin.icon}</span>
              </div>
              <div className="detailTitleGroup-cpT99c">
                <h2 className="detailTitle-X7zIZu">{plugin.name}</h2>
                <p className="detailDescription-kBy0Ek">{plugin.description}</p>
                <p className="detailPublisher-VPxyqw">{plugin.publisher}</p>
              </div>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div className="detailDocSection-Mil5SR">
            <div className="detailDescriptionCard-FtwEk8">
              <p className="detailDescriptionText-apMOdF">
                {plugin.name} 是一个强大的插件，旨在提升你的开发效率。它提供了丰富的功能集，帮助你更快地编写代码、调试程序、生成文档等。无论是新手还是专家开发者，都能从中受益。
              </p>
            </div>
            <div className="detailMarkdownCard-kxmm37">
              <div className="detailMarkdownInner-grR20b">
                <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 8px 0' }}>
                  可用技能
                </h3>
                <div>
                  <div className="skillsGrid-qtaVFy">
                    {skillTemplates.map((s) => (
                      <div key={s.name} className="skillCard-ZYOuVS">
                        <div className="skillCardHeader-W2sqOU">
                          <div className="cardIcon-ZFp7gR" style={{ alignItems: 'center', display: 'flex', fontSize: '24px', justifyContent: 'center' }}>
                            {s.icon}
                          </div>
                          <div className="skillCardBody-xR2lZi">
                            <span className="skillCardName-gePr1m">{s.name}</span>
                            <span className="skillCardDesc-_LvYuN">{s.desc}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="detailActionBar-BhqrLr">
            <div className="detailActionRight-CxGqmX" style={{ marginLeft: 'auto' }}>
              <button
                className="detailBtnPrimary-NtBx72"
                disabled={installing}
                onClick={() => setInstalling(true)}
                style={{
                  background: 'var(--bg-bg-invert)', borderRadius: '4px',
                  color: 'var(--text-text-onaccent)', cursor: installing ? 'not-allowed' : 'pointer',
                  display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
                  height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
                  opacity: installing ? 0.6 : 1,
                }}
              >
                {installing ? '安装中...' : '+ 安装技能'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}