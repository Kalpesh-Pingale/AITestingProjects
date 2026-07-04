I want you to create a simple **RAG Explorer** application.

The source files will be available in the `data` folder. I will provide a simple PDF file, which is a Product Requirements Document for `vwo.com`.

Your task is to build a React-based UI that demonstrates how the ingestion and retrieval process works.

The application should do the following:

1. Read the PDF file from the `data/data` folder.
2. Split the PDF content into chunks.
3. Generate embeddings for those chunks using the **Nomic Embed** embedding model.
4. Store the embeddings automatically in a local **ChromaDB** instance.
5. Provide a query interface where I can ask questions related to the PDF.
6. For every query, retrieve and display the **tgetting op 4 relevant chunks** fetched from the document.
7. Use **Groq** as the LLM provider, with the **OpenGPT 120B** model, to generate the final answer based on the retrieved chunks.
8. The UI should clearly showcase the complete RAG flow: PDF ingestion, chunking, embedding, storage, retrieval, and answer generation.

The goal of this application is to demonstrate how a basic RAG pipeline works end-to-end using a local vector database and a React frontend.
