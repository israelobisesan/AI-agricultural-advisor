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
        themeToggleBtn.textContent = '☀️';
    } else {
        document.body.classList.add('dark-mode');
        themeToggleBtn.textContent = '🌙';
    }

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

    // --- Sidebar Toggle Functionality ---
    const allToggleButtons = document.querySelectorAll('.sidebar-toggle, .chat-header-toggle');

    allToggleButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation(); // Prevent event from bubbling
            sidebar.classList.toggle('collapsed');
        });
    });

    // Close sidebar if user clicks outside it (but only if it's open on mobile)
    document.addEventListener('click', (e) => {
        if (window.innerWidth <= 768) { // Only auto-close on mobile
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
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: userMessage,
                    session_id: sessionId,
                    image_filename: uploadedImagePath,
                    language: selectedLanguage
                })
            });

            const data = await response.json();

            loadingMessage.remove();
            appendMessageToChat('ai', data.response, false, data.audio_url);
            
            /*// New addition: automatically play the audio if a URL is provided
            if (data.audio_url) {
                audioPlayer.src = data.audio_url;
                audioPlayer.play().catch(e => console.error("Audio playback failed:", e));
            }*/

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

        // --- Chat History Loading and Display ---
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
        
        // ✅ Replace small white box with modern audio player
        if (sender === 'ai' && audioUrl) {
            const audioWrapper = document.createElement('div');
            audioWrapper.classList.add('audio-player');

            audioWrapper.innerHTML = `
                <button class="play-btn">▶</button>
                <button class="stop-btn">⏹</button>
                <input type="range" class="progress-bar" value="0" min="0" max="100">
                <audio src="${audioUrl}" preload="auto"></audio>
            `;

            const audio = audioWrapper.querySelector('audio');
            const playBtn = audioWrapper.querySelector('.play-btn');
            const stopBtn = audioWrapper.querySelector('.stop-btn');
            const progressBar = audioWrapper.querySelector('.progress-bar');

            // Play/Pause logic
            playBtn.addEventListener('click', () => {
                if (audio.paused) {
                    audio.play();
                    playBtn.textContent = '⏸';
                } else {
                    audio.pause();
                    playBtn.textContent = '▶';
                }
            });

            // Stop logic
            stopBtn.addEventListener('click', () => {
                audio.pause();
                audio.currentTime = 0;
                playBtn.textContent = '▶';
            });

            // Update progress bar
            audio.addEventListener('timeupdate', () => {
                progressBar.value = (audio.currentTime / audio.duration) * 100;
            });

            // Seek
            progressBar.addEventListener('input', () => {
                audio.currentTime = (progressBar.value / 100) * audio.duration;
            });

            messageDiv.appendChild(audioWrapper);
        }

        messageContainer.appendChild(messageDiv);
        chatHistory.appendChild(messageContainer);
        chatHistory.scrollTop = chatHistory.scrollHeight;

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

    // Load chat history on page load
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
                        appendMessageToChat(msg.sender, msg.text);
                    });
                }
            })
            .catch(error => {
                console.error('Error fetching chat history:', error);
            });
    }
});