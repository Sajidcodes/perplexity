"use client";

import { useState, FormEvent, ChangeEvent } from 'react';
import Header from '@/components/Header';
// import InputBar from '@/components/InputBar';
import MessageArea from '@/components/MessageArea';


interface InputBarProps {
  currentMessage: string;
  setCurrentMessage: (msg: string) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
}

interface SearchInfo {
  stages: string[]; // searching, reading, writing; maintaining it to show UI in a certain way
  query: string;
  urls?: string[];
  error?: string;
}

interface Message {
  id: number;
  content: string;
  isUser: boolean;
  type: string;
  isLoading?: boolean; // when the request hits the server and before LLM starts generating something
  searchInfo?: SearchInfo;
}

const InputBar: React.FC<InputBarProps> = ({ currentMessage, setCurrentMessage, onSubmit }) => {
  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
      setCurrentMessage(e.target.value);
  };

  return (
      <form onSubmit={onSubmit} className="flex p-2 border-t border-gray-200">
          <input
              type="text"
              value={currentMessage}
              onChange={handleChange}
              placeholder="Type a message..."
              className="flex-1 p-2 border rounded"
          />
          <button type="submit" className="ml-2 px-4 py-2 bg-blue-500 text-white rounded">
              Send
          </button>
      </form>
  );
};

const Home = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      content: 'Hi there, how can I help you?',
      isUser: false,
      type: 'message',
    },
  ]);
  const [currentMessage, setCurrentMessage] = useState<string>("");
  const [checkpointId, setCheckpointId] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    if (!currentMessage.trim()) return;

    const newMessageId =
      messages.length > 0 ? Math.max(...messages.map((msg) => msg.id)) + 1 : 1;

    // Add user message
    setMessages((prev) => [
      ...prev,
      {
        id: newMessageId,
        content: currentMessage,
        isUser: true,
        type: 'message',
      },
    ]);

    const userInput = currentMessage;
    setCurrentMessage(""); // clear input

    try {
      // AI response placeholder
      const aiResponseId = newMessageId + 1;
      setMessages((prev) => [
        ...prev,
        {
          id: aiResponseId,
          content: "",
          isUser: false,
          type: 'message',
          isLoading: true,
          searchInfo: { stages: [], query: "", urls: [] },
        },
      ]);

      // SSE URL
      let url = `https://perplexity-latest-9xq1.onrender.com/chat_stream/${encodeURIComponent(userInput)}`;
      if (checkpointId) url += `?checkpoint_id=${encodeURIComponent(checkpointId)}`;

      const eventSource = new EventSource(url);
      let streamedContent = "";
      let searchData: SearchInfo | undefined = undefined;
      let hasReceivedContent = false;

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          switch (data.type) {
            case 'checkpoint':
              setCheckpointId(data.checkpoint_id);
              break;

            case 'content':
              streamedContent += data.content;
              hasReceivedContent = true;
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === aiResponseId
                    ? { ...msg, content: streamedContent, isLoading: false }
                    : msg
                )
              );
              break;

            case 'search_start':
              searchData = { stages: ['searching'], query: data.query, urls: [] };
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === aiResponseId
                    ? { ...msg, content: streamedContent, searchInfo: searchData || undefined, isLoading: false }
                    : msg
                )
              );
              break;

            case 'search_results':
              const urls = typeof data.urls === 'string' ? JSON.parse(data.urls) : data.urls;
              searchData = {
                stages: searchData ? [...searchData.stages, 'reading'] : ['reading'],
                query: searchData?.query || "",
                urls,
              };
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === aiResponseId
                    ? { ...msg, content: streamedContent, searchInfo: searchData || undefined, isLoading: false }
                    : msg
                )
              );
              break;

            case 'search_error':
              searchData = {
                stages: searchData ? [...searchData.stages, 'error'] : ['error'],
                query: searchData?.query || "",
                error: data.error,
                urls: [],
              };
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === aiResponseId
                    ? { ...msg, content: streamedContent, searchInfo: searchData || undefined, isLoading: false }
                    : msg
                )
              );
              break;

            case 'end':
              if (searchData) {
                const finalSearchInfo = {
                  ...searchData,
                  stages: [...searchData.stages, 'writing'],
                };
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === aiResponseId
                      ? { ...msg, searchInfo: finalSearchInfo, isLoading: false }
                      : msg
                  )
                );
              }
              eventSource.close();
              break;
          }
        } catch (err) {
          console.error("Error parsing event data:", err, event.data);
        }
      };

      eventSource.onerror = (err) => {
        console.error("EventSource error:", err);
        eventSource.close();
        if (!streamedContent) {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === aiResponseId
                ? { ...msg, content: "Sorry, there was an error processing your request.", isLoading: false }
                : msg
            )
          );
        }
      };
    } catch (err) {
      console.error("Error setting up EventSource:", err);
      setMessages((prev) => [
        ...prev,
        {
          id: newMessageId + 1,
          content: "Sorry, there was an error connecting to the server.",
          isUser: false,
          type: 'message',
          isLoading: false,
        },
      ]);
    }
  };

  return (
    <div className="flex justify-center bg-gray-100 min-h-screen py-8 px-4">
      <div className="w-[70%] bg-white flex flex-col rounded-xl shadow-lg border border-gray-100 overflow-hidden h-[90vh]">
        <Header />
        <MessageArea messages={messages} />
        <InputBar currentMessage={currentMessage} setCurrentMessage={setCurrentMessage} onSubmit={handleSubmit} />
      </div>
    </div>
  );
};

export default Home;
