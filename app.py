import streamlit as st
import speech_recognition as sr
from gtts import gTTS
import io
import difflib
import re
import wave # 新增：用于精准读取音频真实时长
import eng_to_ipa as ipa

# 1. 宽屏页面及初始化状态 (Session State 升级版)
st.set_page_config(page_title="AI口语私教", page_icon="🎙️", layout="wide")

# 初始化各种记忆变量，防止数据丢失和重复记录
if 'score_history' not in st.session_state:
    st.session_state.score_history = []
if 'attempt_count' not in st.session_state:
    st.session_state.attempt_count = 0
if 'last_audio_hash' not in st.session_state:
    st.session_state.last_audio_hash = None # 用于校验是否是新录音
if 'eval_result' not in st.session_state:
    st.session_state.eval_result = None # 用于缓存上次的评测结果，防止页面刷新重复调接口

# --- 侧边栏：学习数据看板 ---
with st.sidebar:
    st.header("📈 你的学习轨迹")
    if st.session_state.attempt_count == 0:
        st.info("还没有练习记录，快去录制你的第一次跟读吧！")
    else:
        st.metric("总练习次数", f"{st.session_state.attempt_count} 次")
        st.metric("历史最高分", f"{max(st.session_state.score_history)}%")
        st.line_chart(st.session_state.score_history, height=200)
        st.caption("折线图展示了你每一次真实录音的准确率变化。")
        
        if st.button("🗑️ 清空历史记录"):
            st.session_state.score_history = []
            st.session_state.attempt_count = 0
            st.session_state.last_audio_hash = None
            st.session_state.eval_result = None
            st.rerun()

# --- 主界面 ---
st.title("🎙️ AI 口语影子跟读与多维评测系统")
st.write("自主输入任何英文，AI将同步开启【标准原音 + 录音对比 + 国际音标辅导 + 流利度语速诊断】！")

mode = st.radio("请选择语料来源：", ["📚 使用内置经典语料", "✍️ 自定义输入文本"], horizontal=True)

target_text = ""
if mode == "📚 使用内置经典语料":
    texts = {
        "经典演讲 (马丁·路德·金)": "I have a dream that one day this nation will rise up.",
        "电影台词 (阿甘正传)": "Life was like a box of chocolates. You never know what you're gonna get.",
        "日常交际 (餐厅点餐)": "I would like to order a steak with some mashed potatoes, please."
    }
    selected_task = st.selectbox("请选择：", list(texts.keys()))
    target_text = texts[selected_task]
else:
    target_text = st.text_area("请在此粘贴或输入你想练习的英语文本：", value="Practice makes perfect.")

if target_text.strip():
    st.info(f"**当前练习文本：** {target_text}")
    
    st.write("▶️ **第一步：听原音 (Listen)**")
    tts = gTTS(text=target_text, lang='en')
    mp3_fp = io.BytesIO()
    tts.write_to_fp(mp3_fp)
    st.audio(mp3_fp, format='audio/mp3')

    st.divider()

    st.write("🎙️ **第二步：录制你的跟读 (Shadowing)**")
    audio_bytes = st.audio_input("点击麦克风图标开始录音")
    
    if audio_bytes:
        # 获取当前录音的唯一哈希值
        current_audio_hash = hash(audio_bytes.getvalue())
        
        # 核心逻辑：只有当这是一段全新的录音时，才重新进行 AI 评测
        if current_audio_hash != st.session_state.last_audio_hash:
            st.write("⏳ AI 正在深度分析你的发音与流利度...")
            
            # 1. 修复 Bug 1：从音频文件头精准提取物理时长
            audio_bytes.seek(0)
            try:
                with wave.open(audio_bytes, 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    record_duration = round(frames / float(rate), 2)
            except Exception:
                record_duration = 3.0 # 备用保险方案
            
            audio_bytes.seek(0) # 提取完时长后，指针归零，交给语音识别
            
            r = sr.Recognizer()
            try:
                with sr.AudioFile(audio_bytes) as source:
                    audio_data = r.record(source)
                
                user_transcript = r.recognize_google(audio_data, language="en-US")
                
                # 更严格的文本清洗逻辑
                def clean_text(text):
                    # 移除非字母数字字符，统一小写
                    return re.sub(r'[^\w\s]', '', text).lower().split()
                    
                target_words = clean_text(target_text)
                user_words = clean_text(user_transcript)
                
                matcher = difflib.SequenceMatcher(None, target_words, user_words)
                html_output = []
                correct_count = 0
                
                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    words_list = target_words[i1:i2]
                    words = " ".join(words_list)
                    if tag == 'equal':
                        html_output.append(f"<span style='color:green; font-weight:bold;'>{words}</span>")
                        correct_count += (i2 - i1)
                    elif tag in ('replace', 'delete'):
                        ipa_transcriptions = []
                        for single_word in words_list:
                            raw_ipa = ipa.convert(single_word)
                            cleaned_ipa = f"[{raw_ipa}]" if "*" not in raw_ipa else ""
                            # 修复 Bug 2：只给单词加删除线，音标保持正常显示
                            ipa_transcriptions.append(
                                f"<span style='color:red; text-decoration: line-through;'>{single_word}</span> "
                                f"<small style='color:#FFB6C1; text-decoration: none;'>{cleaned_ipa}</small>"
                            )
                        failed_phrase = " ".join(ipa_transcriptions)
                        html_output.append(failed_phrase)
                        
                total_words = max(len(target_words), 1)
                accuracy = int((correct_count / total_words) * 100)
                
                # 计算语速
                user_word_count = len(user_words)
                wpm = int((user_word_count / record_duration) * 60) if record_duration > 0 else 0
                
                if wpm >= 130:
                    fluency_status = "⚡ 接近/等同母语者语速 (流利度极佳)"
                elif 90 <= wpm < 130:
                    fluency_status = "🎯 标准口语语速 (正常且流畅)"
                else:
                    fluency_status = "🐢 语速偏慢 (可能存在犹豫、卡顿，需多练)"
                
                # 将正确的结果存入系统记忆
                st.session_state.score_history.append(accuracy)
                st.session_state.attempt_count += 1
                st.session_state.last_audio_hash = current_audio_hash
                st.session_state.eval_result = {
                    "accuracy": accuracy,
                    "wpm": wpm,
                    "fluency_status": fluency_status,
                    "html_output": " ".join(html_output),
                    "record_duration": record_duration,
                    "user_transcript": user_transcript
                }
                
            except sr.UnknownValueError:
                st.error("❌ AI 听不清，请靠麦克风近一些，声音大一些，再试一次！")
                st.stop() # 停止运行，不记录错误数据 (修复 Bug 4)
            except sr.RequestError:
                st.error("❌ 网络连接故障，无法接通语音服务，请刷新。")
                st.stop()
                
        # === 渲染评测结果区 (直接从缓存读取，防止重复刷新) ===
        if st.session_state.eval_result:
            res = st.session_state.eval_result
            
            st.subheader("📊 AI 多维诊断报告")
            st.caption(f"**AI 识别内容日志：** {res['user_transcript']}")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(label="发音准确率", value=f"{res['accuracy']}%")
            with col2:
                st.metric(label="跟读语速", value=f"{res['wpm']} WPM", delta="Words per Minute")
            with col3:
                st.markdown(f"**流利度评级：**\n\n<span style='color:#1E90FF; font-weight:bold; font-size:20px;'>{res['fluency_status']}</span>", unsafe_allow_html=True)
                
            st.write("---")
            
            st.markdown("🎯 **第1维·发音定位与 IPA 辅导（绿色为准确，红色/粉字为读错和音标）：**")
            st.markdown(f"<div style='font-size: 18px; line-height: 1.8;'>{res['html_output']}</div>", unsafe_allow_html=True)
            
            st.markdown(f"💡 **第2维·流利度分析：** 你的这次发音总共用时 **{res['record_duration']} 秒**。")
            
            # 添加关于 ASR 准确度瓶颈的学术说明 (应对 Bug 3 的答辩话术)
            st.info("ℹ️ **学术说明 (Disclaimer)：** 本系统底层调用通用级 ASR (自动语音识别) 引擎。ASR 致力于语义理解而非音素级纠错，因此可能对轻微的口音具有‘宽容度’。在真实教学环境中，可将其作为形成性评价工具，而非终结性考评工具。")
            
            if res['accuracy'] == 100:
                st.balloons()