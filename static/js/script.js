document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatHistory = document.getElementById('chat-history');
    const themeToggleBtn = document.getElementById('theme-toggle');
    const uploadImageBtn = document.getElementById('upload-image-button');
    const imageInput = document.getElementById('image-input');
    const sidebar = document.getElementById('sidebar');
    const sidebarToggleBtn = document.getElementById('sidebar-toggle');
    const languageSelect = document.getElementById('language-select');
    const sessionIdInput = document.getElementById('session-id');
    const speechToggleBtn = document.getElementById('speech-toggle');
    const audioPlayer = new Audio();

    let uploadedImagePath = null;
    let selectedLanguage = languageSelect.value;
    let recognition;
    let isRecordingLocked = false;
    let longPressTimeout;

    // --- Theme Toggle Functionality ---
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light') {
        document.body.classList.add('light-mode');
        if (themeToggleBtn) themeToggleBtn.textContent = '☀️';
    } else {
        document.body.classList.add('dark-mode');
        if (themeToggleBtn) themeToggleBtn.textContent = '🌙';
    }

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', () => {
            if (document.body.classList.contains('dark-mode')) {
                document.body.classList.replace('dark-mode', 'light-mode');
                themeToggleBtn.textContent = '☀️';
                localStorage.setItem('theme', 'light');
            } else {
                document.body.classList.replace('light-mode', 'dark-mode');
                themeToggleBtn.textContent = '🌙';
                localStorage.setItem('theme', 'dark');
            }
        });
    }

    // --- Sidebar Toggle Functionality ---
    sidebarToggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        sidebar.classList.toggle('collapsed');
    });

    // Close sidebar when clicking outside (mobile only)
    document.addEventListener('click', (e) => {
        if (window.innerWidth <= 768) {
            if (!sidebar.contains(e.target) && !e.target.closest('.sidebar-toggle')) {
                sidebar.classList.add('collapsed');
            }
        }
    });

    // --- Language Selector Functionality ---
    languageSelect.addEventListener('change', (e) => {
        selectedLanguage = e.target.value;
        if (recognition) {
            recognition.lang = selectedLanguage === 'yo' ? 'yo-NG' : 'en-US';
        }
    });

    // --- Speech-to-Text (STT) Functionality ---
    if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = selectedLanguage === 'yo' ? 'yo-NG' : 'en-US';

        let finalTranscript = '';

        recognition.onstart = () => {
            speechToggleBtn.classList.add('listening');
            userInput.placeholder = "Listening...";
        };

        recognition.onend = () => {
            speechToggleBtn.classList.remove('listening');
            userInput.placeholder = "Type your message...";
            if (finalTranscript !== '') {
                userInput.value = finalTranscript;
                resizeInput();
            }
        };

        recognition.onresult = (event) => {
            let interimTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript + ' ';
                } else {
                    interimTranscript += transcript;
                }
            }
            userInput.value = finalTranscript + interimTranscript;
            resizeInput();
        };

        recognition.onerror = (event) => {
            console.error('Speech recognition error:', event.error);
            speechToggleBtn.classList.remove('listening');
            userInput.placeholder = "Type your message...";
            alert("Speech recognition error: " + event.error);
        };

        speechToggleBtn.addEventListener('mousedown', () => {
            finalTranscript = '';
            try {
                if (!isRecordingLocked) {
                    recognition.start();
                    longPressTimeout = setTimeout(() => {
                        isRecordingLocked = true;
                        speechToggleBtn.classList.add('locked');
                        userInput.placeholder = "Locked and listening...";
                    }, 500);
                }
            } catch (e) {
                console.error("Speech recognition start error:", e);
            }
        });

        speechToggleBtn.addEventListener('mouseup', () => {
            clearTimeout(longPressTimeout);
            if (isRecordingLocked) {
                recognition.stop();
                isRecordingLocked = false;
                speechToggleBtn.classList.remove('locked');
                chatForm.dispatchEvent(new Event('submit'));
            } else {
                recognition.stop();
                if (finalTranscript !== '') {
                    userInput.value = finalTranscript;
                    resizeInput();
                    chatForm.dispatchEvent(new Event('submit'));
                }
            }
        });

        speechToggleBtn.addEventListener('mouseleave', () => {
            clearTimeout(longPressTimeout);
            if (speechToggleBtn.classList.contains('listening') && !isRecordingLocked) {
                recognition.stop();
                if (finalTranscript !== '') {
                    userInput.value = finalTranscript;
                    resizeInput();
                    chatForm.dispatchEvent(new Event('submit'));
                }
            }
        });

    } else {
        speechToggleBtn.style.display = 'none';
        console.warn('Speech Recognition API not supported in this browser.');
    }

    // --- Resizable Textarea Functionality ---
    function resizeInput() {
        userInput.style.height = 'auto';
        userInput.style.height = userInput.scrollHeight + 'px';
    }
    userInput.addEventListener('input', resizeInput);
    resizeInput();

    // --- Image Upload Functionality ---
    uploadImageBtn.addEventListener('click', () => {
        imageInput.click();
    });

    imageInput.addEventListener('change', async (event) => {
        const file = event.target.files[0];
        if (file) {
            const formData = new FormData();
            formData.append('image', file);

            try {
                const response = await fetch('/api/upload_image', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                if (response.ok) {
                    uploadedImagePath = data.image_filename;
                    appendImageToChat(`/uploads/${uploadedImagePath}`);
                    userInput.placeholder = "Image uploaded. Ask me about it!";
                    userInput.focus();
                } else {
                    console.error('Image upload failed:', data.error);
                    alert('Failed to upload image. Please try again.');
                }
            } catch (error) {
                console.error('Error uploading image:', error);
                alert('An error occurred during image upload.');
            }
        }
    });

    // --- Form Submission Functionality ---
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const userMessage = userInput.value.trim();
        const sessionId = sessionIdInput.value;

        if (!userMessage && !uploadedImagePath) {
            return;
        }

        if (userMessage) {
            appendMessageToChat('user', userMessage);
        }

        const loadingMessage = appendMessageToChat('ai', '...', true);

        userInput.value = '';
        resizeInput();
        userInput.disabled = true;
        chatForm.querySelector('button[type="submit"]').disabled = true;

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage,
                    session_id: sessionId,
                    image_filename: uploadedImagePath,
                    language: selectedLanguage
                })
            });

            const data = await response.json();
            loadingMessage.remove();

            const messageElement = appendMessageToChat('ai', data.response, false, null);
            const audioLoadingIndicator = addAudioLoadingIndicator(messageElement);

            generateAudioInBackground(data.message_id, selectedLanguage, messageElement, audioLoadingIndicator, data.response);

            uploadedImagePath = null;
            userInput.placeholder = 'Type your message...';

        } catch (error) {
            console.error('Error during AI response generation:', error);
            loadingMessage.remove();
            appendMessageToChat('ai', 'Sorry, I could not process your request at this time.');
        } finally {
            userInput.disabled = false;
            chatForm.querySelector('button[type="submit"]').disabled = false;
            userInput.focus();
        }
    });

    // --- Generate Audio in Background ---
    async function generateAudioInBackground(messageId, language, messageElement, audioLoadingIndicator, textFallback) {
        try {
            const body = messageId
                ? { message_id: messageId, language: language }
                : { text: textFallback, language: language };
            const response = await fetch('/api/generate_audio', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            const data = await response.json();

            if (audioLoadingIndicator) audioLoadingIndicator.remove();

            if (data.audio_urls && data.audio_urls.length > 0) {
                addAudioPlayerToMessage(messageElement, data.audio_urls);
            } else {
                addAudioError(messageElement);
            }

        } catch (error) {
            console.error('Audio generation error:', error);
            if (audioLoadingIndicator) audioLoadingIndicator.remove();
            addAudioError(messageElement);
        }
    }

    // --- Add Audio Loading Indicator ---
    function addAudioLoadingIndicator(messageElement) {
        const indicator = document.createElement('div');
        indicator.className = 'audio-loading-indicator';
        indicator.innerHTML = '🔊 <span class="loading-dots">Loading audio...</span>';
        indicator.style.fontSize = '12px';
        indicator.style.color = '#666';
        indicator.style.marginTop = '8px';
        indicator.style.fontStyle = 'italic';

        const messageDiv = messageElement.querySelector('.message');
        messageDiv.appendChild(indicator);
        return indicator;
    }

    // --- Add Audio Player(s) to Existing Message ---
    function addAudioPlayerToMessage(messageElement, audioUrls) {
        const messageDiv = messageElement.querySelector('.message');
        const urls = Array.isArray(audioUrls) ? audioUrls : [audioUrls];
        const showLabels = urls.length > 1;
        const audioElements = [];

        urls.forEach((audioUrl, index) => {
            const audioWrapper = document.createElement('div');
            audioWrapper.classList.add('audio-player');

            if (showLabels) {
                const label = document.createElement('div');
                label.textContent = `Part ${index + 1} of ${urls.length}`;
                label.style.fontSize = '11px';
                label.style.color = '#888';
                label.style.marginBottom = '4px';
                audioWrapper.appendChild(label);
            }

            const controls = document.createElement('div');
            controls.innerHTML = `
                <button class="play-btn">▶</button>
                <button class="stop-btn">⏹</button>
                <input type="range" class="progress-bar" value="0" min="0" max="100">
                <audio src="${audioUrl}" preload="auto"></audio>
            `;

            const audio = controls.querySelector('audio');
            const playBtn = controls.querySelector('.play-btn');
            const stopBtn = controls.querySelector('.stop-btn');
            const progressBar = controls.querySelector('.progress-bar');

            audioElements.push(audio);

            playBtn.addEventListener('click', () => {
                if (audio.paused) {
                    audio.play();
                    playBtn.textContent = '⏸';
                } else {
                    audio.pause();
                    playBtn.textContent = '▶';
                }
            });

            stopBtn.addEventListener('click', () => {
                audio.pause();
                audio.currentTime = 0;
                playBtn.textContent = '▶';
            });

            audio.addEventListener('timeupdate', () => {
                progressBar.value = (audio.currentTime / audio.duration) * 100 || 0;
            });

            audio.addEventListener('ended', () => {
                playBtn.textContent = '▶';
                const next = audioElements[index + 1];
                if (next) {
                    const wrapper = next.closest('.audio-player');
                    const nextBtn = wrapper ? wrapper.querySelector('.play-btn') : null;
                    next.play();
                    if (nextBtn) nextBtn.textContent = '⏸';
                }
            });

            progressBar.addEventListener('input', () => {
                audio.currentTime = (progressBar.value / 100) * audio.duration;
            });

            audioWrapper.appendChild(controls);
            messageDiv.appendChild(audioWrapper);
        });
    }

    // --- Add Audio Error Message ---
    function addAudioError(messageElement) {
        const messageDiv = messageElement.querySelector('.message');
        const errorDiv = document.createElement('div');
        errorDiv.className = 'audio-error';
        errorDiv.innerHTML = '⚠️ Audio unavailable';
        errorDiv.style.fontSize = '12px';
        errorDiv.style.color = '#999';
        errorDiv.style.marginTop = '8px';
        messageDiv.appendChild(errorDiv);
    }

    // --- Append Message to Chat ---
    // audioUrl here is the raw value from the DB — a JSON string like '["url1","url2"]'
    // or null, or a legacy plain URL string.
    function appendMessageToChat(sender, text, isLoading = false, audioUrl = null) {
        const messageContainer = document.createElement('div');
        const messageDiv = document.createElement('div');

        messageContainer.classList.add('message-container', `${sender}-message-container`);
        messageDiv.classList.add('message', `${sender}-message`);

        if (isLoading) {
            messageDiv.innerHTML = '<span class="loading-dots">...</span>';
        } else {
            messageDiv.innerHTML = parseMarkdown(text);
        }

        messageContainer.appendChild(messageDiv);
        chatHistory.appendChild(messageContainer);
        chatHistory.scrollTop = chatHistory.scrollHeight;

        // Attach audio player(s) if audio exists
        if (sender === 'ai' && audioUrl) {
            let urls = [];
            if (Array.isArray(audioUrl)) {
                urls = audioUrl;
            } else {
                try {
                    // Stored as JSON string in DB e.g. '["url1","url2"]'
                    urls = JSON.parse(audioUrl);
                } catch {
                    // Legacy: plain single URL string
                    urls = [audioUrl];
                }
            }
            if (urls.length > 0) {
                addAudioPlayerToMessage(messageContainer, urls);
            }
        }

        return messageContainer;
    }

    function appendImageToChat(src) {
        const messageContainer = document.createElement('div');
        const messageDiv = document.createElement('div');
        const image = document.createElement('img');

        messageContainer.classList.add('message-container', 'user-message-container');
        messageDiv.classList.add('message', 'user-message');
        image.classList.add('image-message');
        image.src = src;

        messageDiv.appendChild(image);
        messageContainer.appendChild(messageDiv);
        chatHistory.appendChild(messageContainer);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function parseMarkdown(text) {
        let formattedText = text;
        formattedText = formattedText.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        formattedText = formattedText.replace(/\*(.*?)\*/g, '<em>$1</em>');
        formattedText = formattedText.replace(/\n/g, '<br>');
        return formattedText;
    }

    // --- Load Chat History on Page Load ---
    const currentSessionId = sessionIdInput.value;
    if (currentSessionId) {
        fetch(`/api/chat_history/${currentSessionId}`)
            .then(response => response.json())
            .then(data => {
                if (data.messages) {
                    data.messages.forEach(msg => {
                        if (msg.image_filename) {
                            appendImageToChat(`/uploads/${msg.image_filename}`);
                        }
                        // msg.audio_url is the raw JSON string from DB — appendMessageToChat handles parsing
                        appendMessageToChat(msg.sender, msg.text, false, msg.audio_url);
                    });
                }
            })
            .catch(error => {
                console.error('Error fetching chat history:', error);
            });
    }
});