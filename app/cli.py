from app.graph import build_graph, ChatState


def main():
    graph = build_graph()
    state: ChatState = {"messages": []}

    print("LangGraph Routed Chat (with Construction Tools)")
    print("Tools available:")
    print(" - General chat")
    print(" - Feet/Inches measurement converter")
    print(" - Board-foot calculator (e.g., '10 boards of 2x10x16')")
    print(" - Sheet count estimator (e.g., 'How many 4x8 sheets for 720 sq ft?')")
    print(" - Material cost estimator (e.g., '40 sheets at $14 each', '16 boards 2x10x16 at $2.10 per bf')\n")
    print("Type 'exit', 'quit', or 'q' to leave.\n")

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in ("exit", "quit", "q"):
            print("Goodbye 👋")
            break

        state["messages"].append(f"USER: {user_input}")
        state = graph.invoke(state)

        last_message = state["messages"][-1]
        if last_message.startswith("ASSISTANT:"):
            reply = last_message.replace("ASSISTANT:", "Assistant:", 1).strip()
        else:
            reply = last_message

        print(reply)
        print()


if __name__ == "__main__":
    main()
