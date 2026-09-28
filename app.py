"""Streamlit interface preview. No database access or AI API calls yet."""

import streamlit as st


def main() -> None:
    st.set_page_config(page_title="Ask Your Data", page_icon="💬", layout="centered")
    st.title("Ask Your Data")
    st.write("Ask a question. Explore the result. Inspect the SQL.")
    st.info("Preview only. Data questions will be available when the chatbot is connected.")

    with st.sidebar:
        st.header("Your dataset")
        st.write("No dataset connected yet.")
        st.caption("Planned demo: a public or synthetic sales dataset.")

    st.subheader("Questions you will be able to ask")
    st.markdown(
        "- What was our revenue in August 2026?\n"
        "- Which five products generated the most revenue?\n"
        "- How did monthly revenue change over time?"
    )
    st.caption("Available questions will depend on the dataset selected.")

    with st.chat_message("assistant"):
        st.write(
            "Once your data is connected, answers will include the result table, "
            "the SQL used, and relevant definitions."
        )

    st.chat_input("Chat will be available once the dataset is connected", disabled=True)


if __name__ == "__main__":
    main()
