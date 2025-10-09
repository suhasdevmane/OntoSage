// src/components/Home.js
import React from 'react';
// Removed unused Link import to satisfy ESLint
import './Home.css';
import TopNav from './TopNav';


import Apache_Jena from './imgs/Apache_Jena_1.png';
import graphdbImg from './imgs/GraphDB-small.png';
import thingsboardImg from './imgs/thingsboardImg.png';
import pgImg from './imgs/pgadminvala.png';
import adminerImg from './imgs/adminer_hosting.png';
import visualiserImg from './imgs/bldg-removebg-preview.png';
import jupyterImg from './imgs/jupyter-3.png';
import apiImg from './imgs/api-removebg.png';
import Microservicespng from './imgs/services.png';
import OllamaImg from './imgs/ollama.png';
import files from './imgs/folder.png';
import servicespic from './imgs/services.png';
import RasaLogo2 from './imgs/chatbot.png';
import nl2sparql from './imgs/nl2sparql.png';
// Reuse existing API icons for services without specific logos


export default function Home() {
  const openService = url => window.open(url, '_blank');

 const services = [
    // Data & Semantics
    { img: Apache_Jena,    title: "Jena Fuseki Server", text: "Semantic Web Framework",            url: "http://localhost:3030",  width:  "70%", height: "150px" },
    { img: graphdbImg,     title: "GraphDB",            text: "Graph DBMS for SPARQL",            url: "http://localhost:7200",  width:  "70%", height: "150px" },

    // IoT Platform & DB Tools
    { img: thingsboardImg, title: "ThingsBoard Server", text: "IoT Platform",                      url: "http://localhost:8082", width:  "70%", height: "150px" },
    { img: pgImg,          title: "pgAdmin",            text: "Database Management",               url: "http://localhost:5050",  width:  "70%", height: "150px" },
    { img: adminerImg,     title: "Adminer",            text: "Database Management",               url: "http://localhost:8282",  width:  "70%", height: "150px" },

    // Frontend & Notebooks
    { img: visualiserImg,  title: "3D-Abacws Service",  text: "3D Visualization",                  url: "http://localhost:8090",  width:  "70%", height: "150px" },
    { img: jupyterImg,     title: "Jupyter Notebook",   text: "Notebooks for data analysis",       url: "http://localhost:8888",  width:  "70%", height: "150px" },

    // APIs and Microservices
    { img: apiImg,         title: "3D-API",             text: "API for 3D Services",               url: "http://localhost:8091",  width:  "70%", height: "150px" },
    { img: Microservicespng,title: "Microservices",      text: "Analytics and utilities",           url: "http://localhost:6001",  width:  "70%", height: "150px" },
    { img: files,         title: "File Server",        text: "Shared artifacts server",           url: "http://localhost:8080",  width:  "70%", height: "150px" },

    // Conversational stack
    { img: RasaLogo2,        title: "Rasa Server",        text: "Conversational AI",                 url: "http://localhost:5005",  width:  "70%", height: "150px" },
    { img: servicespic,      title: "Action Server",      text: "Rasa custom actions",               url: "http://localhost:5055",  width:  "70%", height: "150px" },
    { img: servicespic,      title: "Duckling",           text: "Entity extraction service",         url: "http://localhost:8000",  width:  "70%", height: "150px" },

    // AI services
    { img: nl2sparql,           title: "NL2SPARQL",          text: "Natural language → SPARQL",         url: "http://localhost:6005",  width:  "70%", height: "150px" },
    { img: OllamaImg,           title: "Ollama (Mistral)",   text: "Local LLM service",                 url: "http://localhost:11434", width:  "70%", height: "150px" },
  ];

  return (
    <div className="home-body">

      {/* 🌊 Wave layers */}
      <div className="wave"></div>
      <div className="wave"></div>
      <div className="wave"></div>
      {/* Navbar */}
      <TopNav />

      {/* Intro */}
      <div className="container mt-4" id="content">
        <h1>Abacws SmartBot – Your Virtual Assistant</h1>
        <p>
          Click on the chat button to start a conversation or select a service below:
        </p>
      </div>

      {/* Services grid */}
      <div className="service-container container" id="content">
        <div className="row row-cols-1 row-cols-md-2 row-cols-lg-4 g-4">
          {services.map((svc, i) => (
            <div className="col" key={i}>
              <div className="card-transparent service-card">
                <img
                  src={svc.img}
                  className="card-img-top"
                  alt={svc.title}
                    // apply your custom dimensions here:
                    style={{
                      width: svc.width,
                      height: svc.height,
                      objectFit: 'cover',
                      marginBottom: '10px'
                    }}
                />
                <div className="card-body">
                  <h5 className="card-title">{svc.title}</h5>
                  <p className="card-text">{svc.text}</p>
                  <div className="card-footer">
                    <button
                      className="btn btn-primary"
                      onClick={() => openService(svc.url)}
                    >
                      Open Service
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
